"""
回傳一律是 dict —— 呼叫端拿到就能直接當 JSON 丟出去。
"""

from typing import Any, Literal

from psycopg import Connection, sql
from psycopg.rows import dict_row

Verdict = Literal["fit", "unfit", "filtered"]

VERDICTS: dict[str, sql.SQL] = {
    "fit": sql.SQL("status = 'judged' AND fit"),
    "unfit": sql.SQL("status = 'judged' AND NOT fit"),
    "filtered": sql.SQL("status = 'list_rejected'"),
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
    starred,
    first_seen_at,
    judged_at
""")


LIST = sql.SQL("""
    SELECT {columns}
    FROM jobs
    WHERE {where}
    ORDER BY first_seen_at DESC, slug
    LIMIT %(limit)s OFFSET %(offset)s
""")

COUNT = sql.SQL("""
    SELECT
        count(*) FILTER (WHERE {fit})      AS fit,
        count(*) FILTER (WHERE {unfit})    AS unfit,
        count(*) FILTER (WHERE {filtered}) AS filtered
    FROM jobs
""")

UPDATE = sql.SQL("""
    UPDATE jobs SET {target} = %(value)s, updated_at = now()
    WHERE slug = %(slug)s
    RETURNING {columns}
""")


def list_jobs(
    conn: Connection, verdict: Verdict, limit: int, offset: int
) -> list[dict[str, Any]]:
    query = LIST.format(columns=COLUMNS, where=VERDICTS[verdict])
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, {"limit": limit, "offset": offset})
        return cur.fetchall()


def count_jobs(conn: Connection) -> dict[str, int]:
    """三個 tab 各有幾筆。"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(COUNT.format(**VERDICTS))
        return cur.fetchone() or {}


def _update(conn: Connection, slug: str, target: str, value: object) -> dict | None:
    """只有 human_label / starred 兩個欄位走這裡，target 由呼叫端寫死。"""
    query = UPDATE.format(target=sql.Identifier(target), columns=COLUMNS)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, {"value": value, "slug": slug})
        row = cur.fetchone()
    conn.commit()
    return row


def set_label(conn: Connection, slug: str, human_label: bool | None) -> dict | None:
    """語意是「我適合/不適合這個職缺」，不是「llm 判得對不對」。None = 收回標註。"""
    return _update(conn, slug, "human_label", human_label)


def set_star(conn: Connection, slug: str, starred: bool) -> dict | None:
    return _update(conn, slug, "starred", starred)
