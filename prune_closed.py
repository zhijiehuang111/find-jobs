"""
收件匣（判適合、還沒標、沒收藏）-> 重抓 104 detail -> switch = off 的刪掉

用法：
    uv run prune_closed.py           # 只列出關掉的，不刪
    uv run prune_closed.py --apply   # 真的刪
"""

import sys
import time

import httpx

from fetch_104 import SLEEP_SECONDS, fetch_detail
from pipeline import connect

TODO = """
    SELECT slug, raw_detail
    FROM jobs
    WHERE status = 'judged' AND fit AND human_label IS NULL AND NOT starred
    ORDER BY first_seen_at
"""

# 條件再擋一次，檢查途中在網頁上標了或收藏了的不刪
DELETE = """
    DELETE FROM jobs
    WHERE slug = ANY(%(slugs)s) AND human_label IS NULL AND NOT starred
"""


def main() -> None:
    apply = "--apply" in sys.argv[1:]

    with connect() as conn:
        todo = conn.execute(TODO).fetchall()
        print(f"收件匣要檢查 {len(todo)} 筆\n")

        closed: list[str] = []
        skipped = 0
        for i, (slug, detail) in enumerate(todo, 1):
            name = f"{detail['header']['jobName']}（{detail['header']['custName']}）"
            # 只有明確看到 off 才算關掉；打不到或讀不到欄位的一律跳過，寧可留著
            try:
                switch = fetch_detail(slug)["data"]["switch"]
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as err:
                print(f"{i:3}/{len(todo)} ? {name}（{type(err).__name__}: {err}）")
                skipped += 1
            else:
                if switch == "off":
                    closed.append(slug)
                    print(f"{i:3}/{len(todo)} ✗ {name}")
                elif switch != "on":
                    print(f"{i:3}/{len(todo)} ? {name}（switch = {switch!r}）")
                    skipped += 1
            time.sleep(SLEEP_SECONDS)

        print(
            f"\n關掉 {len(closed)} 筆"
            + (f"，查不到 {skipped} 筆沒動" if skipped else "")
        )
        if not closed:
            return
        if not apply:
            print("加 --apply 才會刪")
            return

        deleted = conn.execute(DELETE, {"slugs": closed}).rowcount
        conn.commit()
        print(f"刪了 {deleted} 筆")


if __name__ == "__main__":
    main()
