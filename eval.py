"""
用法：
    uv run eval.py              # 全部計分題，結果寫進 evals/ 並記進 history.tsv
    uv run eval.py 10           # 只跑 10 筆（平均散在整份考卷上），亂試的時候用
    uv run eval.py 10 -m 標題   # 加一句備註，寫進結果檔，之後回頭看得懂這次改了什麼

分數只有在 dataset_sha256 相同時才能互相比。換考卷（加題、改答案）之後，
先用當前這版重跑一次建立新基準線，再開始改東西。
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from judge import (
    MODEL,
    judge,
    load_profile,
    load_rules,
    make_client,
    sha16,
)

DATASET_PATH = Path("private/dataset.jsonl")
RESULTS_DIR = Path("private/evals")
HISTORY_PATH = RESULTS_DIR / "history.tsv"


WORKERS = 8

HISTORY_HEADER = (
    "run_at\tprompt\tprofile\tdataset\tmodel\tn\taccuracy\tprecision\trecall\tnote"
)


@dataclass
class Item:
    """一題：考卷上的一筆職缺 + 跑完之後填上的作答。"""

    slug: str
    url: str
    job: str
    label: str  # 我標的答案
    my_reason: str
    record: dict
    fit: bool | None = None  # LLM 判的，None = 這題爆掉了
    reason: str = ""
    error: str = ""

    @property
    def truth(self) -> bool:
        return self.label == "yes"

    @property
    def correct(self) -> bool:
        return self.fit is not None and self.fit == self.truth


@dataclass
class Metrics:
    """正面類別（yes / 適合）的混淆矩陣。

    precision 低 = 推了一堆我不想投的（每天早上多看幾眼，可以忍）。
    recall 低 = 漏掉我想投的（看不到就是永遠錯過，這個嚴重得多）。
    """

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    errors: list[Item] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.total if self.total else 0.0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0


def read_lines(path: Path) -> list[str]:
    """跟 build_dataset.py 同一個理由：JD 裡有 U+2028，splitlines() 會切壞 JSON。"""
    return path.read_text(encoding="utf-8").split("\n")


def load_dataset() -> list[Item]:
    """讀考卷，只留計分題（label 是 yes / no 的）。"""
    if not DATASET_PATH.exists():
        sys.exit(f"找不到 {DATASET_PATH}，先跑 uv run build_dataset.py。")

    items = []
    for line in filter(None, read_lines(DATASET_PATH)):
        record = json.loads(line)
        if record["label"] not in ("yes", "no"):
            continue
        header = record["detail"]["header"]
        items.append(
            Item(
                slug=record["slug"],
                url=record["url"],
                job=f"{header['jobName']}｜{header['custName']}",
                label=record["label"],
                my_reason=record["reason"],
                record=record,
            )
        )
    if not items:
        sys.exit(f"{DATASET_PATH} 裡沒有計分題，先在 labels.tsv 填 label。")
    return items


def take(items: list[Item], n: int) -> list[Item]:
    """抽 n 題小子集。

    考卷是照 labels.tsv 的順序排的，而我是一區一區標的（一整批 yes、一整批 no），
    直接取前 n 筆會全部是同一個答案。所以平均散開來取，比例才不會歪掉。
    固定取法不隨機 —— 小子集也要能前後比較。
    """
    if n >= len(items):
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def run(items: list[Item], client, rules: str, profile: str) -> None:
    """跑完把結果填回 item。單題爆掉不中斷整場，記下來最後一起報。"""

    def one(item: Item) -> None:
        try:
            result = judge(item.record["detail"], client, rules, profile)
        except Exception as err:  # 網路、rate limit、content filter 都算在內
            item.error = f"{type(err).__name__}: {err}"
            return
        item.fit, item.reason = result.fit, result.reason

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i, _ in enumerate(pool.map(one, items), 1):
            print(f"\r  判斷中 {i}/{len(items)}…", end="", flush=True)
    print("\r" + " " * 30 + "\r", end="")


def score(items: list[Item]) -> Metrics:
    metrics = Metrics()
    for item in items:
        if item.fit is None:
            metrics.errors.append(item)
        elif item.fit and item.truth:
            metrics.tp += 1
        elif item.fit and not item.truth:
            metrics.fp += 1
        elif not item.fit and item.truth:
            metrics.fn += 1
        else:
            metrics.tn += 1
    return metrics


def short(digest: str) -> str:
    """給人看的長度。結果檔留 16 碼，印出來和寫進 history 的都取前 8 碼。"""
    return digest[:8]


def print_report(items: list[Item], metrics: Metrics, meta: dict) -> None:
    print(
        f"prompt={short(meta['prompt_sha256'])}"
        f" profile={short(meta['profile_sha256'])}"
        f" dataset={short(meta['dataset_sha256'])}"
        f" model={meta['model']}"
    )
    if meta["subset"]:
        print(f"⚠️ 小子集 {metrics.total} 題，只能跟同樣抽法的小子集比。")

    print(
        f"\n正確率 {metrics.accuracy:.1%}"
        f"（{metrics.tp + metrics.tn}/{metrics.total}）"
        f"｜precision {metrics.precision:.1%}｜recall {metrics.recall:.1%}"
    )
    print("           我標適合   我標不適合")
    print(f"  它判適合    {metrics.tp:>4}      {metrics.fp:>4}")
    print(f"  它判不適合  {metrics.fn:>4}      {metrics.tn:>4}")

    # 錯誤明細。漏掉的（FN）排前面 —— 那是看不到的錯，比多推一筆嚴重。
    wrong = [item for item in items if item.fit is not None and not item.correct]
    wrong.sort(key=lambda item: not item.truth)
    if wrong:
        print(f"\n❌ 判錯 {len(wrong)} 題")
        for item in wrong:
            kind = "漏掉了" if item.truth else "多推了"
            print(f"\n  [{kind}] {item.job}")
            print(f"    我：{item.my_reason or '（沒寫理由）'}")
            print(f"    它：{item.reason}")
            print(f"    {item.url}")

    if metrics.errors:
        print(f"\n⚠️ {len(metrics.errors)} 題沒跑完，不計分：")
        for item in metrics.errors:
            print(f"  {item.job}\n    {item.error}")


def write_result(items: list[Item], metrics: Metrics, meta: dict) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{meta['run_at'].replace(':', '').replace('-', '')[:15]}.json"
    payload = {
        "meta": meta,
        "metrics": {
            "accuracy": round(metrics.accuracy, 4),
            "precision": round(metrics.precision, 4),
            "recall": round(metrics.recall, 4),
            "tp": metrics.tp,
            "fp": metrics.fp,
            "fn": metrics.fn,
            "tn": metrics.tn,
            "failed": len(metrics.errors),
        },
        "items": [
            {
                "slug": item.slug,
                "url": item.url,
                "job": item.job,
                "label": item.label,
                "my_reason": item.my_reason,
                "fit": item.fit,
                "reason": item.reason,
                "correct": item.correct,
                "error": item.error,
            }
            for item in items
        ],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def append_history(metrics: Metrics, meta: dict) -> None:
    """一次一行，方便直接 cat 看版本之間的變化。小子集不記，免得混進來當基準。

    prompt / profile 換了 hash=換了一版，就是拿來跟舊的比分數的。
    dataset 換了 hash=考卷變了，跟之前的分數不能比，要重跑一次建新基準線。
    hash 只認內容（改個錯字也會變），「改了什麼」看 -m 的 note。
    """
    if not HISTORY_PATH.exists():
        HISTORY_PATH.write_text(HISTORY_HEADER + "\n", encoding="utf-8")
    row = "\t".join(
        [
            meta["run_at"],
            short(meta["prompt_sha256"]),
            short(meta["profile_sha256"]),
            short(meta["dataset_sha256"]),
            meta["model"],
            str(metrics.total),
            f"{metrics.accuracy:.3f}",
            f"{metrics.precision:.3f}",
            f"{metrics.recall:.3f}",
            meta["note"].replace("\t", " "),
        ]
    )
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(row + "\n")


def parse_args(argv: list[str]) -> tuple[int | None, str]:
    n, note = None, ""
    args = list(argv)
    if "-m" in args:
        i = args.index("-m")
        note = " ".join(args[i + 1 :])
        args = args[:i]
    if args:
        if not args[0].isdigit():
            sys.exit(__doc__)
        n = int(args[0])
    return n, note


def main() -> None:
    n, note = parse_args(sys.argv[1:])

    graded = load_dataset()
    items = take(graded, n) if n else graded
    client = make_client()
    rules, profile = load_rules(), load_profile()

    meta = {
        "run_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": MODEL,
        # 跟 pipeline 寫進 DB 的是同一組 hash（judge.sha16），對得起來。
        "prompt_sha256": sha16(rules),
        "profile_sha256": sha16(profile),
        "dataset_sha256": sha16(DATASET_PATH.read_bytes()),
        "dataset_graded": len(graded),
        "n": len(items),
        "subset": len(items) < len(graded),
        "note": note,
    }

    run(items, client, rules, profile)
    metrics = score(items)
    print_report(items, metrics, meta)

    path = write_result(items, metrics, meta)
    if not meta["subset"]:
        append_history(metrics, meta)
    print(f"\n結果寫進 {path}")


if __name__ == "__main__":
    main()
