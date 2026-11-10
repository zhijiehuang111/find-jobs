"""
給前端讀的 HTTP 介面。

用法：
    uv run fastapi dev api.py                     # 開發：自動重載，http://127.0.0.1:8000/docs
    uv run fastapi run api.py --host 127.0.0.1    # 正式：--host 不能省

`fastapi run` 預設綁 0.0.0.0，在 VPS 上等於把 API 直接曝到公網、繞過 nginx 的
basic auth。要跟 Postgres 一樣只綁 127.0.0.1，得自己指定 --host。
"""

import logging
from collections.abc import AsyncGenerator, Callable, Iterator
from contextlib import AbstractContextManager, asynccontextmanager
from datetime import datetime
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from psycopg import Connection
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

import queries
from company_research import KnownFact, ResearchItem, research
from db import conninfo
from fetch_104 import fetch_company
from queries import Label, Sort, Verdict

log = logging.getLogger(__name__)
# 公司調查的過程（每次工具呼叫一行）印到 stderr，VPS 上會進 journalctl。
# 只把 company_research 開到 INFO，其他套件（像 httpx 每個請求一行）維持 WARNING
logging.basicConfig(format="%(levelname)s %(message)s")
logging.getLogger("company_research").setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """pipeline.py 那種開一條用完就關的連線 CLI 適用，API 不行 —— 這裡掛一個 pool。"""
    with ConnectionPool(conninfo(), min_size=1, max_size=4, open=True) as pool:
        pool.wait(timeout=10)
        app.state.pool = pool
        yield


app = FastAPI(title="find-jobs", lifespan=lifespan)


def get_conn() -> Iterator[Connection]:
    with app.state.pool.connection() as conn:
        yield conn


Db = Annotated[Connection, Depends(get_conn)]

Connect = Callable[[], AbstractContextManager[Connection]]


def get_connect() -> Connect:
    """給背景任務自己開連線用。request 的那條在回應送出後就還回 pool 了，不能留給它。"""
    return app.state.pool.connection


# 預設的調查項目，內容照 #11。寫在呼叫端這邊，公司調查模組不認識它們（ADR 0002）
RESEARCH_ITEMS = [
    ResearchItem(
        key="what_it_does",
        name="在做什麼",
        question="這家公司賣什麼、賣給誰、怎麼賺錢？",
        criteria=(
            "用沒有這個產業背景的人也看得懂的白話寫，專有名詞要順便解釋。"
            "固定分三行：「一句話」不超過 40 字，說清楚賣什麼給誰；"
            "「客戶」說主要客戶的類型，代工或接案的公司要說是哪一類客戶；"
            "「怎麼賺錢」說主要收入來源，例如賣產品、訂閱、專案、代工。"
            "總共不超過 150 字，不列產品清單，不寫沿革和願景。"
        ),
    ),
    ResearchItem(
        key="recent_news",
        name="近期動向",
        question="這家公司一年內有哪些看得出營運狀況的消息？",
        criteria=(
            "只收一年內、主角是這家公司或標明的關聯實體的消息，類型限："
            "營收或獲利的變化；募資、併購、上市櫃；裁員、組織調整或大量擴編；"
            "重大合作或主力產品上市。得獎、公益、行銷活動、徵才廣告不算。"
            "最多 3 則，挑最能看出公司現在好不好的，每則一句話，附日期和來源。"
        ),
    ),
    ResearchItem(
        key="employee_reviews",
        name="員工評價",
        question="在 PTT 上，員工、前員工或面試者怎麼評價這家公司？",
        criteria=(
            "只用 PTT：search 的 sites 填 ptt.cc，"
            "用一般人稱呼這家公司的簡稱搜「簡稱 工作」「簡稱 面試」。"
            "只收發文日期在三年內的文章，要用 read_page 讀全文，推文也算。"
            "整理成重點，有寫到才列：薪資、工時加班、團隊氛圍和管理、面試流程；"
            "每點附發文日期，發文者有寫職位的話也標出來。"
            "公司自己寫的福利介紹和徵才文案不算；搜 2 次沒找到就回報查不到。"
        ),
    ),
]


# 104 公司簡介裡要給 agent 看的欄位。福利（welfare）不給：那是公司自己寫的，
# 不能當員工評價，給了反而容易被誤用
PROFILE_FIELDS = {
    "industryDesc": "產業",
    "custLink": "官網",
    "profile": "公司介紹",
    "product": "主要商品／服務",
}


def company_profile(company_url: str | None) -> list[KnownFact]:
    """104 公司簡介當已知資料，讓 agent 一開始就知道品牌和產品。
    抓不到就不帶，調查照常進行。"""
    if not company_url:
        return []
    try:
        data = fetch_company(company_url)
        lines = [
            f"{label}：{data[key]}"
            for key, label in PROFILE_FIELDS.items()
            if data.get(key)
        ]
    except Exception:
        # 連不上、回應格式不對都算，不能讓整次調查跟著失敗
        log.exception("抓 104 公司簡介失敗：%s", company_url)
        return []
    if not lines:  # 公司不存在時 104 也回 200，只是欄位都是 null
        return []
    return [
        KnownFact(content="104 公司簡介\n" + "\n".join(lines), source_url=company_url)
    ]


class LabelBody(BaseModel):
    human_label: Label | None
    human_note: str | None = None


class StarBody(BaseModel):
    starred: bool


@app.get("/api/jobs")
def list_jobs(
    conn: Db,
    verdict: Verdict | None = None,
    starred: bool | None = None,
    labeled: bool | None = None,
    sort: Sort = "first_seen",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict]:
    """都不給就是全部：
    收件匣    ?verdict=fit&labeled=false
    收藏      ?starred=true&sort=starred
    不適合    ?verdict=unfit
    規則刷掉  ?verdict=filtered
    """
    return queries.list_jobs(conn, verdict, starred, labeled, sort, limit, offset)


@app.get("/api/stats")
def stats(conn: Db) -> dict[str, int]:
    return queries.count_jobs(conn)


def _found(row: dict | None, slug: str) -> dict:
    if row is None:
        raise HTTPException(status_code=404, detail=f"沒有這筆職缺：{slug}")
    return row


@app.post("/api/jobs/{slug}/label")
def set_label(conn: Db, slug: str, body: LabelBody) -> dict:
    row = queries.set_label(conn, slug, body.human_label, body.human_note)
    return _found(row, slug)


@app.post("/api/jobs/{slug}/star")
def set_star(conn: Db, slug: str, body: StarBody) -> dict:
    return _found(queries.set_star(conn, slug, body.starred), slug)


def run_research(
    company: str, started_at: datetime, connect: Connect, company_url: str | None
) -> None:
    """背景跑公司調查。調查要跑好幾分鐘，連線等報告出來再開，不要一路佔著。
    出錯就存成失敗，不然會一直停在調查中、前端也沒辦法重試。"""
    try:
        report = research(company, RESEARCH_ITEMS, company_profile(company_url))
    except Exception as err:
        log.exception("公司調查失敗：%s", company)
        with connect() as conn:
            queries.fail_research(
                conn, company, started_at, f"{type(err).__name__}: {err}"
            )
        return
    with connect() as conn:
        queries.finish_research(
            conn, company, started_at, report.model_dump(mode="json"), report.model
        )


@app.post("/api/jobs/{slug}/research")
def start_research(
    conn: Db,
    connect: Annotated[Connect, Depends(get_connect)],
    background: BackgroundTasks,
    slug: str,
) -> dict:
    """開始調查這筆職缺的公司，馬上回「調查中」，調查在背景跑。
    已經在調查中就直接回現在的狀態，不再開一次。"""
    row = _found(queries.start_research(conn, slug), slug)
    if row.pop("started"):
        background.add_task(
            run_research,
            row["company"],
            row["started_at"],
            connect,
            queries.company_url(conn, slug),
        )
    return row


@app.get("/api/jobs/{slug}/research")
def get_research(conn: Db, slug: str) -> dict:
    """這筆職缺的公司的調查報告。每個項目補上名稱，前端不用自己對 key。"""
    row = _found(queries.get_research(conn, slug), slug)
    if row["company"] is None:
        raise HTTPException(status_code=404, detail=f"這家公司還沒調查：{slug}")
    if row["report"]:
        names = {item.key: item.name for item in RESEARCH_ITEMS}
        for item in row["report"]["items"]:
            item["name"] = names.get(item["key"], item["key"])
    return row
