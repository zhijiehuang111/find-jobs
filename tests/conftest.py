"""
API 測試打真的 Postgres，SQL 才算有被驗到。

連線寫死在這裡、不讀 .env，測試才不可能清到正式資料。
DB 由 `docker compose up -d postgres-test` 提供，CI 用同一組帳密的 service。
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from api import app, get_conn

TEST_DB_URL = "postgresql://test:test@127.0.0.1:55432/find_jobs_test"
SCHEMA = Path(__file__).parent.parent / "find_jobs.sql"


@pytest.fixture(scope="session")
def schema() -> None:
    """用 find_jobs.sql 建表，schema 寫錯這裡就會炸。"""
    try:
        conn = psycopg.connect(TEST_DB_URL, autocommit=True)
    except psycopg.OperationalError as err:
        pytest.fail(
            f"連不上測試 DB，先跑 `docker compose up -d postgres-test`：{err}",
            pytrace=False,
        )
    with conn:
        conn.execute("DROP TABLE IF EXISTS jobs")
        conn.execute(SCHEMA.read_bytes())


@pytest.fixture
def db(schema: None) -> Iterator[psycopg.Connection]:
    """每個測試從空表開始。"""
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE jobs")
        yield conn


@pytest.fixture
def client(db: psycopg.Connection) -> Iterator[TestClient]:
    """不用 `with TestClient(...)`，lifespan 不會跑，也就不會去讀 .env 開 pool。"""

    def test_conn() -> Iterator[psycopg.Connection]:
        with psycopg.connect(TEST_DB_URL) as conn:
            yield conn

    app.dependency_overrides[get_conn] = test_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def add_job(db: psycopg.Connection) -> Callable[..., str]:
    """塞一筆職缺，回傳 slug。age_days 越大，first_seen_at 越舊。"""

    def add(
        slug: str,
        *,
        fit: bool = True,
        rejected: bool = False,
        human_label: str | None = None,
        human_note: str | None = None,
        starred: bool = False,
        starred_at: datetime | None = None,
        age_days: int = 0,
    ) -> str:
        now = datetime.now(UTC)
        db.execute(
            """
            INSERT INTO jobs (slug, status, rejected_by, raw_list, raw_detail,
                              fit, reason, prompt_sha256, profile_sha256, model,
                              human_label, human_note, starred, starred_at,
                              first_seen_at)
            VALUES (%(slug)s, %(status)s, %(rejected_by)s, %(raw_list)s, %(raw_detail)s,
                    %(fit)s, %(reason)s, %(hash)s, %(hash)s, %(model)s,
                    %(human_label)s, %(human_note)s, %(starred)s, %(starred_at)s,
                    %(first_seen_at)s)
            """,
            {
                "slug": slug,
                "status": "list_rejected" if rejected else "judged",
                "rejected_by": "salary_monthly" if rejected else None,
                "raw_list": Jsonb(
                    {
                        "jobName": "後端工程師",
                        "custName": "某某科技",
                        "jobAddrNoDesc": "台北市信義區",
                        "appearDate": "20261101",
                        "salaryLow": 60000,
                        "salaryHigh": 80000,
                    }
                ),
                "raw_detail": None
                if rejected
                else Jsonb({"jobDetail": {"salary": "月薪60,000~80,000元"}}),
                "fit": None if rejected else fit,
                "reason": None if rejected else "理由",
                "hash": None if rejected else "abc",
                "model": None if rejected else "test-model",
                "human_label": human_label,
                "human_note": human_note,
                "starred": starred,
                "starred_at": starred_at,
                "first_seen_at": now - timedelta(days=age_days),
            },
        )
        return slug

    return add
