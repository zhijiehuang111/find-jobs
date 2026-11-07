"""
在職缺上按「調查公司」：API 開背景調查、存報告、列表帶狀態。

DB 用真的，research() 換成假的（不打 OpenAI、Tavily）。
TestClient 會在回應之前把背景任務跑完，所以 POST 完馬上就能檢查結果。
"""

import pytest

import api
from company_research import ItemAnswer, Report

COMPANY = "○○科技股份有限公司"


class FakeResearch:
    """記下被要求調查哪些公司，回一份固定的報告。found 設成 False 就每項都查不到。"""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.companies: list[str] = []
        self.found = True
        monkeypatch.setattr(api, "research", self)

    def __call__(self, company: str, items, known, **_) -> Report:
        self.companies.append(company)
        return Report(
            company=company,
            items=[
                ItemAnswer(
                    key=item.key,
                    status="found",
                    answer="做假的雲端服務",
                    sources=["https://example.com/about"],
                )
                if self.found
                else ItemAnswer(key=item.key, status="not_found", answer="", sources=[])
                for item in items
            ],
            model="fake-model",
            tool_calls=2,
            input_tokens=100,
            output_tokens=10,
        )


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeResearch:
    return FakeResearch(monkeypatch)


def job(client, slug: str) -> dict:
    return next(j for j in client.get("/api/jobs").json() if j["slug"] == slug)


def test_not_researched_job_lists_without_status(client, add_job):
    add_job("abc", company=COMPANY)

    assert job(client, "abc")["research_status"] is None
    assert job(client, "abc")["research_finished_at"] is None


def test_research_saves_report_and_list_shows_done(client, add_job, fake):
    add_job("abc", company=COMPANY)

    started = client.post("/api/jobs/abc/research")

    assert started.status_code == 200
    assert started.json()["status"] == "running"

    research = client.get("/api/jobs/abc/research").json()
    assert research["company"] == COMPANY
    assert research["status"] == "done"
    assert research["model"] == "fake-model"
    assert research["finished_at"] is not None
    [item] = research["report"]["items"]
    assert item["key"] == "what_it_does"
    assert item["name"] == "在做什麼"
    assert item["answer"] == "做假的雲端服務"
    assert item["sources"] == ["https://example.com/about"]

    listed = job(client, "abc")
    assert listed["research_status"] == "done"
    assert listed["research_finished_at"] is not None


def test_not_found_item_is_reported_as_not_found(client, add_job, fake):
    add_job("abc", company=COMPANY)
    fake.found = False

    client.post("/api/jobs/abc/research")

    research = client.get("/api/jobs/abc/research").json()
    assert research["status"] == "done"
    [item] = research["report"]["items"]
    assert item["name"] == "在做什麼"
    assert item["status"] == "not_found"
    assert item["sources"] == []


def test_jobs_of_same_company_share_one_report(client, add_job, fake):
    add_job("first", company=COMPANY)
    add_job("second", company=COMPANY)
    add_job("other", company="△△有限公司")

    client.post("/api/jobs/first/research")

    assert fake.companies == [COMPANY]
    assert client.get("/api/jobs/second/research").json()["status"] == "done"
    assert job(client, "second")["research_status"] == "done"
    assert job(client, "other")["research_status"] is None


@pytest.mark.parametrize("method", ["post", "get"])
def test_unknown_slug_is_404(client, db, fake, method):
    response = client.request(method, "/api/jobs/nope/research")

    assert response.status_code == 404
    assert "nope" in response.json()["detail"]
    assert fake.companies == []


def test_report_of_company_not_researched_yet_is_404(client, add_job):
    add_job("abc", company=COMPANY)

    response = client.get("/api/jobs/abc/research")

    assert response.status_code == 404
    assert "還沒調查" in response.json()["detail"]
