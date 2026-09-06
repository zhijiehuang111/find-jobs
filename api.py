"""
給前端讀的 HTTP 介面。

用法：
    uv run fastapi dev api.py                     # 開發：自動重載，http://127.0.0.1:8000/docs
    uv run fastapi run api.py --host 127.0.0.1    # 正式：--host 不能省

`fastapi run` 預設綁 0.0.0.0，在 VPS 上等於把 API 直接曝到公網、繞過 nginx 的
basic auth。要跟 Postgres 一樣只綁 127.0.0.1，得自己指定 --host。
"""

import os
import sys
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from psycopg import Connection
from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

import queries
from queries import Verdict


def conninfo() -> str:
    load_dotenv()
    try:
        return make_conninfo(
            host="127.0.0.1",
            port=os.environ["POSTGRES_PORT"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            dbname=os.environ["POSTGRES_DB"],
        )
    except KeyError as err:
        sys.exit(f".env 少了 {err.args[0]}，docker-compose.yml 要的那四個都得有。")


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


class LabelBody(BaseModel):
    human_label: bool | None


class StarBody(BaseModel):
    starred: bool


@app.get("/api/jobs")
def list_jobs(
    conn: Db,
    verdict: Verdict = "fit",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict]:
    return queries.list_jobs(conn, verdict, limit, offset)


@app.get("/api/stats")
def stats(conn: Db) -> dict[str, int]:
    return queries.count_jobs(conn)


def _found(row: dict | None, slug: str) -> dict:
    if row is None:
        raise HTTPException(status_code=404, detail=f"沒有這筆職缺：{slug}")
    return row


@app.post("/api/jobs/{slug}/label")
def set_label(conn: Db, slug: str, body: LabelBody) -> dict:
    return _found(queries.set_label(conn, slug, body.human_label), slug)


@app.post("/api/jobs/{slug}/star")
def set_star(conn: Db, slug: str, body: StarBody) -> dict:
    return _found(queries.set_star(conn, slug, body.starred), slug)
