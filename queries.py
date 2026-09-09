"""
回傳一律是 dict —— 呼叫端拿到就能直接當 JSON 丟出去。
"""

from typing import Any, Literal

from psycopg import Connection, sql
from psycopg.rows import dict_row

Verdict = Literal["fit", "unfit", "filtered"]
Label = Literal["yes", "no", "unsure"]
Sort = Literal["first_seen", "starred"]

VERDICTS: dict[str, sql.SQL] = {
    "fit": sql.SQL("status = 'judged' AND fit"),
    "unfit": sql.SQL("status = 'judged' AND NOT fit"),
    "filtered": sql.SQL("status = 'list_rejected'"),
}

SORTS: dict[str, sql.SQL] = {
    "first_seen": sql.SQL("first_seen_at DESC, slug"),
    "starred": sql.SQL("starred_at DESC NULLS LAST, slug"),
}

# 攤平在 SQL 裡做完
COLUMNS = sql.SQL("""
    slug,
    'https://www.104.com.tw/job/' || slug        AS url,
    raw_list ->> 'jobName'                       AS job_name,
    raw_list ->> 'custName'                      AS cust_name,
    raw_list ->> 'jobAddrNoDesc'                 AS address,
    raw_list ->> 'appearDate'                    AS appear_date,
    (raw_list ->> 'salaryLow')::int              AS salary_low,
    (raw_list ->> 'salaryHigh')::int             AS salary_high,
    raw_detail -> 'jobDetail' ->> 'salary'       AS salary,
    status,
    rejected_by,
    fit,
    reason,
    human_label,
    human_note,
    starred,
    starred_at,
    first_seen_at,
    judged_at
""")


LIST = sql.SQL("""
    SELECT {columns}
    FROM jobs
    WHERE {where}
    ORDER BY {order}
    LIMIT %(limit)s OFFSET %(offset)s
""")

COUNT = sql.SQL("""
    SELECT
        count(*) FILTER (WHERE {fit})      AS fit,
        count(*) FILTER (WHERE {unfit})    AS unfit,
        count(*) FILTER (WHERE {filtered}) AS filtered,
        count(*) FILTER (WHERE {fit} AND human_label IS NULL)      AS inbox,
        count(*) FILTER (WHERE {unfit} AND human_label IS NULL)    AS unfit_open,
        count(*) FILTER (WHERE {filtered} AND human_label IS NULL) AS filtered_open,
        count(*) FILTER (WHERE starred)    AS starred
    FROM jobs
""")

LABEL = sql.SQL("""
    UPDATE jobs SET
        human_label = %(label)s,
        human_note  = CASE
            WHEN %(label)s::text IS NULL                     THEN NULL
            WHEN %(label)s::text = 'yes' AND fit             THEN NULL
            WHEN %(label)s::text = 'no'  AND fit IS NOT TRUE THEN NULL
            ELSE %(note)s
        END,
        updated_at  = now()
    WHERE slug = %(slug)s
    RETURNING {columns}
""")

STAR = sql.SQL("""
    UPDATE jobs SET
        starred    = %(starred)s,
        starred_at = CASE WHEN %(starred)s THEN coalesce(starred_at, now()) END,
        updated_at = now()
    WHERE slug = %(slug)s
    RETURNING {columns}
""")


def _where(
    verdict: Verdict | None, starred: bool | None, labeled: bool | None
) -> sql.Composable:
    """verdict / starred / labeled 是正交的三個條件，不能擠在同一個參數。"""
    parts: list[sql.Composable] = []
    if verdict:
        parts.append(VERDICTS[verdict])
    if starred is not None:
        parts.append(sql.SQL("starred") if starred else sql.SQL("NOT starred"))
    if labeled is not None:
        parts.append(
            sql.SQL("human_label IS NOT NULL")
            if labeled
            else sql.SQL("human_label IS NULL")
        )
    return sql.SQL(" AND ").join(parts) if parts else sql.SQL("TRUE")


def list_jobs(
    conn: Connection,
    verdict: Verdict | None,
    starred: bool | None,
    labeled: bool | None,
    sort: Sort,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    query = LIST.format(
        columns=COLUMNS,
        where=_where(verdict, starred, labeled),
        order=SORTS[sort],
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, {"limit": limit, "offset": offset})
        return cur.fetchall()


def count_jobs(conn: Connection) -> dict[str, int]:
    """每個 tab 各有幾筆。"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(COUNT.format(**VERDICTS))
        return cur.fetchone() or {}


def _returning(conn: Connection, query: sql.SQL, params: dict) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query.format(columns=COLUMNS), params)
        row = cur.fetchone()
    conn.commit()
    return row


def set_label(
    conn: Connection, slug: str, human_label: Label | None, human_note: str | None
) -> dict | None:
    """語意是「我適合/不適合這個職缺」，不是「llm 判得對不對」。None = 收回標註。"""
    return _returning(
        conn, LABEL, {"label": human_label, "note": human_note, "slug": slug}
    )


def set_star(conn: Connection, slug: str, starred: bool) -> dict | None:
    return _returning(conn, STAR, {"starred": starred, "slug": slug})
