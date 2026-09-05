"""
    labels.tsv     你寫的。url / label / reason / 職稱，一行一個職缺
    dataset.jsonl  工具產的。原始 detail + 你的 label，一行一題
用法：
    uv run build_dataset.py

先把網址一行一個貼進 labels.tsv -> 跑一次（抓 detail，把職稱補在行尾）->
**游標移到網址後面**打 label 和 reason -> 再跑一次。之後加新職缺也是一樣。
"""

import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

from fetch_104 import DROP_FIELDS, SLEEP_SECONDS, fetch_detail

LABELS_PATH = Path("private/labels.tsv")
DATASET_PATH = Path("private/dataset.jsonl")

VALID_LABELS = ("yes", "no", "unsure")

HEADER = "# 網址（你貼）\tlabel\treason（你打，接在網址後面）\t職稱（工具填）"
SKELETON = f"""{HEADER}
# label 填 yes / no / unsure —— 自己也猶豫的填 unsure，不計分
# 先把網址一行一個全部貼上，跑一次讓工具補上職稱，再回來標
"""


def read_lines(path: Path) -> list[str]:
    """一定要用 split("\\n")，不能用 splitlines()。

    104 的 JD 裡真的有 U+2028（LINE SEPARATOR），而 splitlines() 除了 \\n 之外
    還會在 U+2028 / U+0085 / \\x0b 這些字元上斷行 —— 一筆 JSON 被切成兩半，
    解析就會噴 Unterminated string，而且檔案本身看起來完全正常。
    """
    return path.read_text(encoding="utf-8").split("\n")


def slug_of(url: str) -> str:
    """https://www.104.com.tw/job/8f8rh?jobsource=xxx -> 8f8rh"""
    return url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]


@dataclass
class Row:
    url: str
    label: str
    reason: str
    job: str  # 職稱｜公司。工具填的，讓你標註時看得懂這行是誰

    @property
    def slug(self) -> str:
        return slug_of(self.url)


def read_labels(jobs: dict[str, str]) -> list[str | Row]:
    """讀 labels.tsv。註解和空行原樣留著，等一下要寫回去。

    切法不靠 Tab，因為編輯器按 Tab 鍵打出來的常常是空格：
    網址不含空白，所以第一段空白之前一定是網址；職稱是工具自己寫的，
    先整段拿掉，剩下的第一個字就是 label、其餘全是理由。
    """
    entries: list[str | Row] = []
    for line in read_lines(LABELS_PATH):
        if not line.strip() or line.lstrip().startswith("#"):
            entries.append(line)
            continue

        parts = re.split(r"\s+", line.strip(), maxsplit=1)
        url, rest = parts[0], parts[1] if len(parts) > 1 else ""

        job = jobs.get(slug_of(url), "")
        if job:
            rest = rest.replace(job, " ")
        tail = re.split(r"\s+", rest.strip(), maxsplit=1)
        label, reason = tail[0], tail[1].strip() if len(tail) > 1 else ""
        entries.append(Row(url=url, label=label, reason=reason, job=job))
    return entries


def validate(rows: list[Row]) -> None:
    """有問題就整個停下來，什麼都還沒寫出去，改完再跑就好。"""
    seen: set[str] = set()
    for row in rows:
        if "104.com.tw/job/" not in row.url:
            sys.exit(
                f"這不像 104 職缺網址：{row.url}\n  一行只能有一個網址，而且要放在最前面。"
            )
        if row.label and row.label not in VALID_LABELS:
            sys.exit(
                f"label 只能填 {' / '.join(VALID_LABELS)}，但這行填的是「{row.label}」：\n  {row.job or row.url}"
            )
        if row.slug in seen:
            sys.exit(f"同一個職缺貼了兩次：{row.url}")
        seen.add(row.slug)


def read_dataset() -> dict[str, dict]:
    if not DATASET_PATH.exists():
        return {}
    lines = read_lines(DATASET_PATH)
    return {record["slug"]: record for record in map(json.loads, filter(None, lines))}


def title_of(record: dict) -> str:
    header = record["detail"]["header"]
    return f"{header['jobName']}｜{header['custName']}".replace("\t", " ")


def fetch_missing(rows: list[Row], dataset: dict[str, dict]) -> list[str]:
    """抓還沒有 detail 的職缺，塞進 dataset。回傳抓失敗的網址。"""
    missing = [row for row in rows if row.slug not in dataset]
    if not missing:
        return []

    print(f"要抓 {len(missing)} 筆新職缺的 detail…")
    failed: list[str] = []
    for i, row in enumerate(missing, 1):
        time.sleep(SLEEP_SECONDS)
        try:
            data = fetch_detail(row.slug)["data"]
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as err:
            print(
                f"  {i:3}/{len(missing)} ✗ {row.url}（{type(err).__name__}）—— 可能已經下架"
            )
            failed.append(row.url)
            continue
        dataset[row.slug] = {
            "slug": row.slug,
            "url": row.url,
            "label": "",
            "reason": "",
            "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "detail": {k: v for k, v in data.items() if k not in DROP_FIELDS},
        }
        print(f"  {i:3}/{len(missing)} {data['header']['jobName']}")
    return failed


def write_dataset(rows: list[Row], dataset: dict[str, dict]) -> None:
    """label / reason 以 labels.tsv 為準覆蓋，detail 原封不動。

    先寫暫存檔再換掉，中途死掉不會留下半份考卷。
    """
    for row in rows:
        if record := dataset.get(row.slug):
            record["label"], record["reason"] = row.label, row.reason

    # 依照 labels.tsv 的順序排，diff 才看得懂。tsv 裡刪掉的仍然留著，不主動丟資料。
    order = {row.slug: i for i, row in enumerate(rows)}
    records = sorted(
        dataset.values(), key=lambda record: order.get(record["slug"], len(order))
    )

    tmp = DATASET_PATH.with_suffix(".jsonl.tmp")
    tmp.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    os.replace(tmp, DATASET_PATH)


def write_labels(entries: list[str | Row], dataset: dict[str, dict]) -> None:
    """寫回 labels.tsv，順便把職稱補在行尾。你的 label / reason 原封不動。"""
    lines = []
    for entry in entries:
        if isinstance(entry, str):
            lines.append(entry)
            continue
        if record := dataset.get(entry.slug):
            entry.job = title_of(record)
        cells = [entry.url, entry.label, entry.reason.replace("\t", " "), entry.job]
        while cells and not cells[-1]:
            cells.pop()
        lines.append("\t".join(cells))
    LABELS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def report(rows: list[Row], dataset: dict[str, dict], failed: list[str]) -> None:
    counts = Counter(row.label or "（還沒標）" for row in rows)
    print(
        f"\nlabels.tsv 共 {len(rows)} 筆："
        + "、".join(f"{k} {v}" for k, v in counts.most_common())
    )

    if unlabeled := [row for row in rows if not row.label]:
        print(f"\n還沒標的 {len(unlabeled)} 筆：")
        for row in unlabeled[:10]:
            print(f"  {row.job or row.url}")
        if len(unlabeled) > 10:
            print(f"  …還有 {len(unlabeled) - 10} 筆")

    if failed:
        print(
            f"\n⚠️ 抓不到 {len(failed)} 筆（多半是下架了），從 labels.tsv 拿掉或換一筆："
        )
        for url in failed:
            print(f"  {url}")

    graded = sum(1 for record in dataset.values() if record["label"] in ("yes", "no"))
    digest = hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest()[:16]
    print(
        f"\n✅ {DATASET_PATH}｜{len(dataset)} 筆，其中 {graded} 題計分｜sha256 {digest}"
    )
    print("   eval 結果檔要記這個 hash，對不上就表示考卷變了，分數不能互相比。")


def main() -> None:
    if not LABELS_PATH.exists():
        LABELS_PATH.write_text(SKELETON, encoding="utf-8")
        sys.exit(f"已經建好 {LABELS_PATH}，把 104 職缺網址一行一個貼進去，再跑一次。")

    dataset = read_dataset()
    entries = read_labels({slug: title_of(record) for slug, record in dataset.items()})
    rows = [entry for entry in entries if isinstance(entry, Row)]
    if not rows:
        sys.exit("labels.tsv 裡還沒有職缺網址。")
    validate(rows)

    failed = fetch_missing(rows, dataset)
    write_dataset(rows, dataset)
    write_labels(entries, dataset)
    report(rows, dataset, failed)


if __name__ == "__main__":
    main()
