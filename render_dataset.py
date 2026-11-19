"""
考卷（dataset.jsonl）轉成給人讀的 Markdown，一題一段。

用法：
    uv run render_dataset.py     # 寫出 private/dataset.md

只讀不寫考卷，不打 104、不花錢。md 是產生出來看的，隨時可以重跑，不進 git；
要改 label / reason 就用 slug 回 dataset.jsonl 搜那一行改。
JD 用 jd_to_text()，也就是模型實際看到的那份文字。
"""

import json
import re
from collections import Counter
from pathlib import Path

from judge import jd_to_text

DATASET_PATH = Path("private/dataset.jsonl")
OUTPUT_PATH = Path("private/dataset.md")


def render(records: list[dict]) -> str:
    counts = Counter(r["label"] or "（沒標）" for r in records)
    summary = "、".join(f"{label} {n}" for label, n in counts.items())
    parts = [f"# 考卷（{len(records)} 題：{summary}）"]
    for number, r in enumerate(records, 1):
        header = r["detail"]["header"]
        parts += [
            f"## {number}. {header['jobName']}｜{header['custName']}",
            "\n".join(
                [
                    f"- slug：`{r['slug']}`",
                    f"- label：{r['label']}",
                    f"- reason：{r['reason']}",
                    f"- 網址：{r['url']}",
                    f"- 抓取時間：{r['fetched_at']}",
                ]
            ),
            _fence(jd_to_text(r["detail"])),
        ]
    return "\n\n".join(parts) + "\n"


def _fence(text: str) -> str:
    # 用比內容裡最長的一串 ` 還多一個的 ` 包起來，JD 裡的 ``` 才不會把區塊提早關掉
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def main() -> None:
    # 一定要用 split("\n")：JD 裡有 U+2028，splitlines() 會把一行 JSON 切斷
    lines = DATASET_PATH.read_text(encoding="utf-8").split("\n")
    records = [json.loads(line) for line in lines if line]
    OUTPUT_PATH.write_text(render(records), encoding="utf-8")
    print(f"寫好了：{OUTPUT_PATH}（{len(records)} 題）")


if __name__ == "__main__":
    main()
