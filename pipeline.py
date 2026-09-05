"""
list -> 去重 -> list 過濾 -> detail -> LLM -> DB

用法：
    uv run pipeline.py                  # backend，1 頁
    uv run pipeline.py python           # 換關鍵字
    uv run pipeline.py python 3         # 逛 3 頁列表
    uv run pipeline.py python 3 --force # 連已經判過的也重判（改了 prompt 之後用）
"""

import os
import sys
import time

import httpx
import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from fetch_104 import DROP_FIELDS, SLEEP_SECONDS, fetch_detail, search
from judge import MODEL, judge, load_profile, load_rules, make_client, sha16
from private.filters import JOB_NAME_BLOCKLIST, SALARY_FLOORS

ANNUAL_SPLIT = 300_000
UNBOUNDED = 9_999_999


def _salary_reject(item: dict) -> str | None:
    """拿**級距上限**當閘門：只要摸得到門檻就放行，即使下限很低。"""
    low = item.get("salaryLow") or 0
    high = item.get("salaryHigh") or 0
    if low == 0:
        return None

    unit = "annual" if low >= ANNUAL_SPLIT else "monthly"

    gate = low if high >= UNBOUNDED else high
    return f"salary_{unit}" if gate < SALARY_FLOORS[unit] else None


def list_reject_reason(item: dict) -> str | None:
    """看 list 欄位決定要不要在這裡就刷掉。回傳 rejected_by，通過就回 None。"""
    if JOB_NAME_BLOCKLIST.search(item.get("jobName", "")):
        return "job_name_blocklist"
    return _salary_reject(item)


UPSERT = """
    INSERT INTO jobs (slug, status, rejected_by, raw_list, raw_detail,
                      fit, reason, prompt_sha256, profile_sha256, model, judged_at)
    VALUES (%(slug)s, %(status)s, %(rejected_by)s, %(raw_list)s, %(raw_detail)s,
            %(fit)s, %(reason)s, %(prompt_sha256)s, %(profile_sha256)s, %(model)s,
            CASE WHEN %(status)s = 'judged' THEN now() END)
    ON CONFLICT (slug) DO UPDATE SET
        status         = EXCLUDED.status,
        rejected_by    = EXCLUDED.rejected_by,
        raw_list       = EXCLUDED.raw_list,
        raw_detail     = EXCLUDED.raw_detail,
        fit            = EXCLUDED.fit,
        reason         = EXCLUDED.reason,
        prompt_sha256  = EXCLUDED.prompt_sha256,
        profile_sha256 = EXCLUDED.profile_sha256,
        model          = EXCLUDED.model,
        judged_at      = EXCLUDED.judged_at,
        updated_at     = now()
"""


def connect() -> psycopg.Connection:
    load_dotenv()
    try:
        return psycopg.connect(
            host="127.0.0.1",
            port=os.environ["POSTGRES_PORT"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            dbname=os.environ["POSTGRES_DB"],
        )
    except KeyError as err:
        sys.exit(f".env 少了 {err.args[0]}，docker-compose.yml 要的那四個都得有。")
    except psycopg.OperationalError as err:
        sys.exit(f"連不上 Postgres（{err}）\n  DB 沒起來的話：docker compose up -d")


def collect_list(keyword: str, pages: int) -> dict[str, dict]:
    """逛列表，回傳 {slug: 整筆 list item}。"""
    items: dict[str, dict] = {}
    for page in range(1, pages + 1):
        if page > 1:
            time.sleep(SLEEP_SECONDS)
        payload = search(keyword, page=page)
        for job in payload["data"]:
            slug = job["link"]["job"].rsplit("/", 1)[-1]
            items.setdefault(slug, job)

        pagination = payload["metadata"]["pagination"]
        print(
            f"第 {page}/{pages} 頁：{pagination['count']} 筆（累計去重後 {len(items)}）"
        )
        if page >= pagination["lastPage"]:
            print("    已經是最後一頁")
            break
    return items


def already_seen(conn: psycopg.Connection, slugs: list[str]) -> set[str]:
    """DB 裡已經有的 —— 這些就是可以跳過、不用花 detail 呼叫和 LLM 錢的。"""
    with conn.cursor() as cur:
        cur.execute("SELECT slug FROM jobs WHERE slug = ANY(%s)", (slugs,))
        return {slug for (slug,) in cur.fetchall()}


def _upsert(conn: psycopg.Connection, params: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(UPSERT, params)
    conn.commit()


def save_judged(
    conn: psycopg.Connection,
    slug: str,
    list_item: dict,
    detail: dict,
    verdict,
    hashes: dict[str, str],
) -> None:
    """hashes = 這批用的 prompt / profile 內容 hash"""
    _upsert(
        conn,
        {
            "slug": slug,
            "status": "judged",
            "rejected_by": None,
            "raw_list": Jsonb(list_item),
            "raw_detail": Jsonb(detail),
            "fit": verdict.fit,
            "reason": verdict.reason,
            **hashes,
            "model": MODEL,
        },
    )


def save_list_rejected(
    conn: psycopg.Connection, slug: str, list_item: dict, rejected_by: str
) -> None:
    """list 階段刷掉的也是一筆 row —— 沒跑到的欄位留 NULL。"""
    _upsert(
        conn,
        {
            "slug": slug,
            "status": "list_rejected",
            "rejected_by": rejected_by,
            "raw_list": Jsonb(list_item),
            "raw_detail": None,
            "fit": None,
            "reason": None,
            "prompt_sha256": None,
            "profile_sha256": None,
            "model": None,
        },
    )


def summarise(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*), count(*) FILTER (WHERE fit) FROM jobs WHERE status = 'judged'"
        )

        total, fit = cur.fetchone() or (0, 0)
        cur.execute(
            "SELECT rejected_by, count(*) FROM jobs WHERE status = 'list_rejected'"
            " GROUP BY rejected_by ORDER BY count DESC"
        )
        rejected = cur.fetchall()
    print(f"DB 現況：判過 {total} 筆，其中適合 {fit} 筆")
    if rejected:
        detail = "、".join(f"{rule} {count}" for rule, count in rejected)
        print(f"          list 階段刷掉 {sum(c for _, c in rejected)} 筆（{detail}）")


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv[1:]
    keyword = args[0] if args else "backend"
    pages = int(args[1]) if len(args) > 1 else 1

    with connect() as conn:
        items = collect_list(keyword, pages)
        if not items:
            sys.exit("列表沒抓到東西。")

        seen = set() if force else already_seen(conn, list(items))
        fresh = {slug: item for slug, item in items.items() if slug not in seen}
        print(f"\n列表 {len(items)} 筆，跳過已處理 {len(seen)} 筆")
        if force:
            print("    （--force：略過去重，已判過的會被覆蓋）")

        todo: dict[str, dict] = {}
        for slug, item in fresh.items():
            rejected_by = list_reject_reason(item)
            if rejected_by is None:
                todo[slug] = item
                continue
            save_list_rejected(conn, slug, item, rejected_by)
            print(f"    x {item['jobName']}（{rejected_by}）")
        list_rejected = len(fresh) - len(todo)
        print(f"list 過濾刷掉 {list_rejected} 筆，要抓 detail {len(todo)} 筆")

        if not todo:
            summarise(conn)
            return

        client = make_client()
        rules, profile = load_rules(), load_profile()
        hashes = {"prompt_sha256": sha16(rules), "profile_sha256": sha16(profile)}

        print(
            f"model={MODEL}"
            f" prompt={hashes['prompt_sha256'][:8]}"
            f" profile={hashes['profile_sha256'][:8]}\n"
        )

        fit_count = failed = 0
        for i, (slug, item) in enumerate(todo.items(), 1):
            time.sleep(SLEEP_SECONDS)
            try:
                data = fetch_detail(slug)["data"]
                detail = {k: v for k, v in data.items() if k not in DROP_FIELDS}
                verdict = judge(detail, client, rules, profile)
            except (httpx.HTTPError, KeyError, ValueError, RuntimeError) as err:
                print(
                    f"{i:3}/{len(todo)} ✗ {item['jobName']}（{type(err).__name__}: {err}）"
                )
                failed += 1
                continue

            save_judged(conn, slug, item, detail, verdict, hashes)
            fit_count += verdict.fit
            mark = "✅" if verdict.fit else "❌"
            print(
                f"{i:3}/{len(todo)} {mark} {detail['header']['jobName']}（{detail['header']['custName']}）"
            )
            print(f"        {verdict.reason}")
            if verdict.fit:
                print(f"        https://www.104.com.tw/job/{slug}")

        print(
            f"\n這次寫入 {list_rejected + len(todo) - failed} 筆"
            f"（判斷 {len(todo) - failed} 筆，其中適合 {fit_count} 筆；"
            f"list 刷掉 {list_rejected} 筆）"
            + (f"，失敗 {failed} 筆沒寫入" if failed else "")
        )
        summarise(conn)


if __name__ == "__main__":
    main()
