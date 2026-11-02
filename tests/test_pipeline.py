"""
pipeline 的流程接線：每筆職缺有沒有走對路、DB 裡有沒有存對。

104 和 OpenAI 用假的，DB 用真的。規則也是假的，所以這裡只驗 pipeline 有沒有照規則走。
規則和門檻刻意取成一看就是假的值，不要放 private/filters.py 裡的真實設定（這個 repo 是公開的）。
"""

import re
from collections.abc import Callable
from types import SimpleNamespace

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

import pipeline
from judge import MODEL, Judgement
from pipeline import UNBOUNDED, _salary_reject, run, save_judged, title_reject_reason

FILTERS = SimpleNamespace(
    COMPANY_BLOCK=re.compile("黑名單公司"),
    JOB_NAME_HARD_BLOCK=re.compile("擋掉"),
    JOB_NAME_NON_ENG=re.compile("非工程"),
    JOB_NAME_ENG_GUARD=re.compile("工程師"),
    JOB_NAME_UNWANTED_LANG=re.compile("語言甲"),
    JOB_NAME_WANTED_LANG=re.compile("語言乙"),
    SALARY_FLOORS={"monthly": 77_777, "annual": 777_777},
)


def list_item(slug: str, name: str, *, company: str = "某某科技", low: int = 0) -> dict:
    """104 列表的一筆。low 預設 0 = 面議，薪資過濾會放行。"""
    return {
        "link": {"job": f"https://www.104.com.tw/job/{slug}"},
        "jobName": name,
        "custName": company,
        "salaryLow": low,
        "salaryHigh": low + 10_000 if low else 0,
    }


def detail(name: str) -> dict:
    """104 detail 的回應，放 jd_to_text 會讀的欄位，加一個存檔前要丟掉的。"""
    return {
        "data": {
            "header": {"jobName": name, "custName": "某某科技"},
            "industry": "電腦軟體服務業",
            "employees": "50人",
            "environmentPic": ["https://example.com/a.jpg"],
            "jobDetail": {
                "jobCategory": [],
                "manageResp": "",
                "businessTrip": "",
                "delegatedRecruit": "",
                "jobDescription": "開發後端 API",
            },
            "condition": {
                "workExp": "不拘",
                "edu": "大學",
                "major": [],
                "specialty": [],
                "skill": [],
                "other": "",
            },
        }
    }


class Fake104AndOpenAI:
    """記下打了誰。verdict 依職稱決定：職稱有「不適合」就判 False。"""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.items: list[dict] = []
        self.broken_slugs: set[str] = set()
        self.detail_calls: list[str] = []
        self.llm_calls: list[str] = []
        self.responses = self  # 讓 judge() 的 client.responses.parse 打到這裡

        monkeypatch.setattr(pipeline, "SLEEP_SECONDS", 0)
        monkeypatch.setattr(pipeline, "search", self.search)
        monkeypatch.setattr(pipeline, "fetch_detail", self.fetch_detail)
        monkeypatch.setattr(pipeline, "make_client", lambda: self)
        monkeypatch.setattr(pipeline, "load_rules", lambda: "假 rules")
        monkeypatch.setattr(pipeline, "load_profile", lambda: "假 profile")

    def search(self, keyword: str, order: str, page: int) -> dict:
        return {
            "data": self.items,
            "metadata": {"pagination": {"count": len(self.items), "lastPage": 1}},
        }

    def fetch_detail(self, slug: str) -> dict:
        self.detail_calls.append(slug)
        if slug in self.broken_slugs:
            raise httpx.ConnectError("104 掛了")
        item = next(i for i in self.items if i["link"]["job"].endswith(slug))
        return detail(item["jobName"])

    def parse(self, *, input: str, **_) -> SimpleNamespace:
        self.llm_calls.append(input)
        return SimpleNamespace(
            output_parsed=Judgement(fit="不適合" not in input, reason="假理由")
        )


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Fake104AndOpenAI:
    return Fake104AndOpenAI(monkeypatch)


@pytest.fixture
def row(db: psycopg.Connection) -> Callable[[str], dict | None]:
    def get(slug: str) -> dict | None:
        with db.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM jobs WHERE slug = %s", (slug,))
            return cur.fetchone()

    return get


def test_each_job_goes_down_the_right_path(db, fake, row):
    fake.items = [
        list_item("good", "後端工程師"),
        list_item("nope", "不適合的工程師"),
        list_item("title", "擋掉工程師"),
        list_item("cheap", "後端工程師", low=30_000),
    ]

    run(db, "backend", 1, FILTERS)

    good = row("good")
    assert good["status"] == "judged"
    assert good["fit"] is True
    assert good["reason"] == "假理由"
    assert good["model"] == MODEL
    assert good["prompt_sha256"] and good["profile_sha256"]
    assert good["judged_at"] is not None
    assert "environmentPic" not in good["raw_detail"]

    assert row("nope")["fit"] is False

    cheap = row("cheap")
    assert cheap["status"] == "list_rejected"
    assert cheap["rejected_by"] == "salary_monthly"
    assert cheap["raw_detail"] is None

    assert row("title") is None
    # 被刷掉的不花 detail 和 LLM
    assert sorted(fake.detail_calls) == ["good", "nope"]
    assert len(fake.llm_calls) == 2


def test_second_run_skips_jobs_already_in_db(db, fake):
    fake.items = [
        list_item("good", "後端工程師"),
        list_item("cheap", "後端工程師", low=30_000),
    ]
    run(db, "backend", 1, FILTERS)
    fake.detail_calls.clear()
    fake.llm_calls.clear()

    run(db, "backend", 1, FILTERS)

    assert fake.detail_calls == []
    assert fake.llm_calls == []


def test_failed_job_is_not_saved_and_retried_next_run(db, fake, row):
    fake.items = [
        list_item("broken", "後端工程師"),
        list_item("good", "後端工程師"),
    ]
    fake.broken_slugs = {"broken"}

    run(db, "backend", 1, FILTERS)

    assert row("broken") is None
    assert row("good") is not None

    fake.broken_slugs = set()
    run(db, "backend", 1, FILTERS)

    assert row("broken")["status"] == "judged"


def test_upsert_overwrites_verdict_but_keeps_human_fields(db, add_job, row):
    # 平常走不到：run() 會先跳過 DB 已有的，rejudge.py 用自己的 UPDATE。
    # 只有兩個 pipeline 同時跑才會撞到，所以直接呼叫 save_judged 測
    add_job("job", fit=False, human_label="no", human_note="看過了", starred=True)
    before = row("job")

    save_judged(
        db,
        "job",
        list_item("job", "後端工程師"),
        {"header": {}},
        Judgement(fit=True, reason="新理由"),
        {"prompt_sha256": "new", "profile_sha256": "new"},
    )

    after = row("job")
    assert after["fit"] is True
    assert after["reason"] == "新理由"
    assert after["prompt_sha256"] == "new"
    assert after["human_label"] == "no"
    assert after["human_note"] == "看過了"
    assert after["starred"] is True
    assert after["first_seen_at"] == before["first_seen_at"]
    assert after["updated_at"] > before["updated_at"]


@pytest.mark.parametrize(
    ("name", "company", "expected"),
    [
        ("後端工程師", "黑名單公司", "company_blocklist"),
        ("擋掉工程師", "某某科技", "job_name_blocklist"),
        ("非工程職", "某某科技", "job_name_non_eng"),
        ("非工程部後端工程師", "某某科技", None),
        ("語言甲工程師", "某某科技", "job_name_lang"),
        ("語言甲 / 語言乙工程師", "某某科技", None),
        ("後端工程師", "某某科技", None),
    ],
)
def test_title_reject_reason(name, company, expected):
    item = {"jobName": name, "custName": company}

    assert title_reject_reason(item, FILTERS) == expected


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [
        (0, 0, None),  # 面議
        (60_000, 70_000, "salary_monthly"),
        (60_000, 80_000, None),  # 上限摸得到門檻就放行
        (60_000, UNBOUNDED, "salary_monthly"),  # 「6 萬以上」沒有上限，看下限
        (80_000, UNBOUNDED, None),
        (500_000, 700_000, "salary_annual"),
        (500_000, 800_000, None),
    ],
)
def test_salary_reject(low, high, expected):
    item = {"salaryLow": low, "salaryHigh": high}

    assert _salary_reject(item, FILTERS.SALARY_FLOORS) == expected
