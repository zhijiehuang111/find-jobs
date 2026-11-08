"""
回傳一律是 dict —— 呼叫端拿到就能直接當 JSON 丟出去。
"""

from datetime import datetime
from typing import Any, Literal

from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

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

# 公司調查卡在調查中多久就當作失敗（程式掛了、重啟了，DB 裡就會一直停在 running）。
# 不寫回 DB，讀的時候換算：列表、報告看到的是失敗，再按一次就能重新調查。
# 用到的地方表都叫 r。
STUCK_MINUTES = 10
STUCK = sql.SQL(
    "(r.status = 'running' AND r.started_at < now() - make_interval(mins => {}))"
).format(sql.Literal(STUCK_MINUTES))
RESEARCH_STATUS = sql.SQL("CASE WHEN {stuck} THEN 'failed' ELSE r.status END").format(
    stuck=STUCK
)
RESEARCH_ERROR = sql.SQL("CASE WHEN {stuck} THEN {msg} ELSE r.error END").format(
    stuck=STUCK, msg=sql.Literal(f"超過 {STUCK_MINUTES} 分鐘沒有結果，當作失敗")
)

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
    -- 104 沒填是 0（detail 那邊寫「暫不提供」），轉成 NULL
    NULLIF((raw_list ->> 'employeeCount')::int, 0) AS employee_count,
    status,
    rejected_by,
    fit,
    reason,
    human_label,
    human_note,
    starred,
    starred_at,
    first_seen_at,
    judged_at,
    (SELECT {research_status} FROM company_research r
     WHERE r.company = jobs.raw_list ->> 'custName')   AS research_status,
    (SELECT r.finished_at FROM company_research r
     WHERE r.company = jobs.raw_list ->> 'custName')   AS research_finished_at
""").format(research_status=RESEARCH_STATUS)


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
        starred     = CASE
            WHEN %(label)s::text = 'yes' THEN TRUE
            WHEN human_label = 'yes'
             AND (%(label)s::text = 'no' OR %(label)s::text IS NULL) THEN FALSE
            ELSE starred
        END,
        starred_at  = CASE
            WHEN %(label)s::text = 'yes' THEN coalesce(starred_at, now())
            WHEN human_label = 'yes'
             AND (%(label)s::text = 'no' OR %(label)s::text IS NULL) THEN NULL
            ELSE starred_at
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


# 公司調查：一家公司一列，以 104 的公司名稱（custName）對上職缺，同一家公司的職缺共用。

# 已經有一列時整列重設成新的一輪，但調查中的不動（不然再按一次就多花一次錢），卡住的照樣重設。
# RETURNING 只回傳這次新增或重設的那一列；調查中而沒動到、或 slug 不存在，就什麼都不回。
START_RESEARCH = sql.SQL("""
    INSERT INTO company_research AS r (company, status)
    SELECT raw_list ->> 'custName', 'running' FROM jobs WHERE slug = %(slug)s
    ON CONFLICT (company) DO UPDATE SET
        status      = 'running',
        report      = NULL,
        error       = NULL,
        model       = NULL,
        started_at  = now(),
        finished_at = NULL
    WHERE r.status <> 'running' OR {stuck}
    RETURNING company, status, report, error, model, started_at, finished_at
""").format(stuck=STUCK)

# 只寫自己這一輪（以開始時間認）：卡住的那輪被重試後才跑完，不能蓋掉還在跑的新一輪
THIS_ROUND = sql.SQL(
    "company = %(company)s AND started_at = %(started_at)s AND status = 'running'"
)

FINISH_RESEARCH = sql.SQL("""
    UPDATE company_research SET
        status      = 'done',
        report      = %(report)s,
        model       = %(model)s,
        finished_at = now()
    WHERE {this_round}
""").format(this_round=THIS_ROUND)

FAIL_RESEARCH = sql.SQL("""
    UPDATE company_research SET
        status      = 'failed',
        error       = %(error)s,
        finished_at = now()
    WHERE {this_round}
""").format(this_round=THIS_ROUND)

# jobs 也有 status、model，JOIN 時要帶表名
GET_RESEARCH = sql.SQL("""
    SELECT r.company, {status} AS status, r.report, {error} AS error,
           r.model, r.started_at, r.finished_at
    FROM jobs
    LEFT JOIN company_research r ON r.company = jobs.raw_list ->> 'custName'
    WHERE jobs.slug = %(slug)s
""").format(status=RESEARCH_STATUS, error=RESEARCH_ERROR)


def company_url(conn: Connection, slug: str) -> str | None:
    """這筆職缺的 104 公司頁網址，抓公司簡介用。"""
    row = conn.execute(
        "SELECT raw_list -> 'link' ->> 'cust' FROM jobs WHERE slug = %s", (slug,)
    ).fetchone()
    return row[0] if row else None


def start_research(conn: Connection, slug: str) -> dict | None:
    """把這筆職缺的公司標成調查中。slug 不存在回 None。
    已經在調查中就不動，回傳的 started 是 False，呼叫端不要再開一次調查。"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(START_RESEARCH, {"slug": slug})
        row = cur.fetchone()
    conn.commit()
    if row is not None:
        return {**row, "started": True}
    # 沒開跑：要嘛正在調查中，要嘛 slug 不存在（get_research 回 None）
    current = get_research(conn, slug)
    return None if current is None else {**current, "started": False}


def finish_research(
    conn: Connection,
    company: str,
    started_at: datetime,
    report: dict[str, Any],
    model: str,
) -> None:
    """started_at 是 start_research 回的那個，認得出是哪一輪。"""
    conn.execute(
        FINISH_RESEARCH,
        {
            "company": company,
            "started_at": started_at,
            "report": Jsonb(report),
            "model": model,
        },
    )
    conn.commit()


def fail_research(
    conn: Connection, company: str, started_at: datetime, error: str
) -> None:
    """started_at 同 finish_research。"""
    conn.execute(
        FAIL_RESEARCH,
        {"company": company, "started_at": started_at, "error": error},
    )
    conn.commit()


def get_research(conn: Connection, slug: str) -> dict | None:
    """slug 不存在回 None；職缺在、公司還沒調查過時，company 那幾欄都是 None。"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(GET_RESEARCH, {"slug": slug})
        return cur.fetchone()
