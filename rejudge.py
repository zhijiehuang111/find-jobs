"""
收件匣（判適合、還沒標）-> 用當前的 prompt / profile 重判 -> 只更新判斷欄位

直接讀 DB 裡的 raw_detail，不打 104。手動跑，不進 cron。

用法：
    uv run rejudge.py            # 重判收件匣
    uv run rejudge.py --unfit    # 改成重判「不適合、還沒標」（放寬了規則時用）
    uv run rejudge.py --dry-run  # 只印會重判幾筆，不打 LLM
"""

import sys

import httpx
import openai

from judge import MODEL, judge, load_profile, load_rules, make_client, sha16
from pipeline import connect

# 三個都跟當前版本一樣的就跳過
TODO = """
    SELECT slug, raw_detail
    FROM jobs
    WHERE status = 'judged' AND fit = %(fit)s AND human_label IS NULL
      AND raw_detail IS NOT NULL
      AND (prompt_sha256  IS DISTINCT FROM %(prompt_sha256)s
        OR profile_sha256 IS DISTINCT FROM %(profile_sha256)s
        OR model          IS DISTINCT FROM %(model)s)
    ORDER BY first_seen_at DESC
"""

# 不動標註、收藏；human_label IS NULL 再擋一次，跑到一半在網頁上標了的不蓋掉
UPDATE = """
    UPDATE jobs SET
        fit            = %(fit)s,
        reason         = %(reason)s,
        prompt_sha256  = %(prompt_sha256)s,
        profile_sha256 = %(profile_sha256)s,
        model          = %(model)s,
        judged_at      = now(),
        updated_at     = now()
    WHERE slug = %(slug)s AND human_label IS NULL
"""


def main() -> None:
    dry_run = "--dry-run" in sys.argv[1:]
    unfit = "--unfit" in sys.argv[1:]
    scope = "不適合（還沒標）" if unfit else "收件匣"

    rules, profile = load_rules(), load_profile()
    version = {
        "prompt_sha256": sha16(rules),
        "profile_sha256": sha16(profile),
        "model": MODEL,
    }
    print(
        f"model={MODEL}"
        f" prompt={version['prompt_sha256'][:8]}"
        f" profile={version['profile_sha256'][:8]}"
    )

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(TODO, {**version, "fit": not unfit})
            todo = cur.fetchall()
        print(f"{scope}要重判 {len(todo)} 筆（已經用這一版判過的跳過）\n")
        if dry_run or not todo:
            return

        client = make_client()
        flipped = failed = 0
        for i, (slug, detail) in enumerate(todo, 1):
            name = f"{detail['header']['jobName']}（{detail['header']['custName']}）"
            try:
                verdict = judge(detail, client, rules, profile)
            except (
                openai.OpenAIError,
                httpx.HTTPError,
                KeyError,
                ValueError,
                RuntimeError,
            ) as err:
                print(f"{i:3}/{len(todo)} ✗ {name}（{type(err).__name__}: {err}）")
                failed += 1
                continue

            with conn.cursor() as cur:
                cur.execute(
                    UPDATE,
                    {
                        "slug": slug,
                        "fit": verdict.fit,
                        "reason": verdict.reason,
                        **version,
                    },
                )
            conn.commit()
            flipped += verdict.fit == unfit
            mark = "✅" if verdict.fit else "❌"
            print(f"{i:3}/{len(todo)} {mark} {name}")
            print(f"        {verdict.reason}")

        print(
            f"\n重判 {len(todo) - failed} 筆，"
            + (f"翻回適合 {flipped} 筆" if unfit else f"移出收件匣 {flipped} 筆")
            + (f"，失敗 {failed} 筆沒更新（再跑一次會補）" if failed else "")
        )


if __name__ == "__main__":
    main()
