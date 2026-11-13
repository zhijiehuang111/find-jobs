"""
調查報告和 trace（Report.trace）轉成給人讀的 Markdown。

research_markdown：最上面是最終報告（前端看到的那份）和成本，下面接整段調查過程。
trace 只加標題和排版，裡面的文字原封不動：
- 每個工具呼叫一個標題，後面直接接它的回應（歷史裡平行呼叫是「呼叫、呼叫、回應、回應」）
- 文字都放進程式碼區塊照原樣印，網頁裡的 #、* 不會被當成 Markdown
- 搜尋結果拆成一筆一段
- 加密的思考內容不印，只寫一行說明
"""

import json
import re
from typing import Any

from .research import Report


def research_markdown(report: Report) -> str:
    cost = (
        f"模型 {report.model}｜工具呼叫 {report.tool_calls} 次｜"
        f"input {report.input_tokens} tokens｜output {report.output_tokens} tokens"
    )
    items = [item.model_dump() for item in report.items]
    parts = [f"# {report.company}", "## 最終報告", cost, *_items(items)]
    return "\n\n".join(parts + _trace_parts(report.trace)) + "\n"


def trace_markdown(title: str, trace: list[dict[str, Any]]) -> str:
    return "\n\n".join([f"# {title}", *_trace_parts(trace)]) + "\n"


def _trace_parts(trace: list[dict[str, Any]]) -> list[str]:
    outputs = {
        e["call_id"]: e["output"]
        for e in trace
        if e.get("type") == "function_call_output"
    }
    called = {e["call_id"] for e in trace if e.get("type") == "function_call"}
    parts = []
    number = 0
    for entry in trace:
        kind = entry.get("type") or entry.get("role")
        if kind == "user":
            parts += ["## 任務", _fence(entry["content"])]
        elif kind == "reasoning":
            texts = [s.get("text", "") for s in entry.get("summary") or []]
            parts.append("## 思考")
            parts += [_fence(t) for t in texts] or ["（加密，看不到）"]
        elif kind == "function_call":
            number += 1
            parts += _call(number, entry, outputs.get(entry["call_id"]))
        elif kind == "function_call_output":
            if entry["call_id"] not in called:  # 正常不會發生，但不能漏印
                parts += ["## 工具回應", _fence(entry["output"])]
        else:  # 不認得的種類（例如模型直接回文字）整筆照印
            parts += [
                f"## {kind}",
                _fence(json.dumps(entry, ensure_ascii=False, indent=2)),
            ]
    return parts


def _call(number: int, entry: dict[str, Any], output: str | None) -> list[str]:
    name = entry["name"]
    try:
        args = json.loads(entry["arguments"])
    except json.JSONDecodeError:
        args = None
    if not isinstance(args, dict):  # 參數格式錯誤：標題只放名稱，參數照原樣印
        return [f"## #{number} {name}", _fence(entry["arguments"]), *_output(output)]

    if name == "search":
        sites = args.get("sites") or []
        heading = f"## #{number} search：{args.get('query', '')}"
        if sites:
            heading += f"（只搜 {', '.join(sites)}）"
        return [heading, *_search_output(output)]
    if name == "read_page":
        return [f"## #{number} read_page：{args.get('url', '')}", *_output(output)]
    if name == "submit_report":
        parts = [f"## #{number} submit_report", *_items(args.get("items") or [])]
        if output is not None:
            parts += ["### 檢查結果", _fence(output)]
        return parts
    return [
        f"## #{number} {name}",
        _fence(json.dumps(args, ensure_ascii=False, indent=2)),
        *_output(output),
    ]


def _items(items: list[dict[str, Any]]) -> list[str]:
    parts = []
    for item in items:
        parts.append(f"### {item.get('key')}（{item.get('status')}）")
        if item.get("answer"):
            parts.append(_fence(item["answer"]))
        parts += [f"- {url}" for url in item.get("sources") or []]
    return parts


def _output(output: str | None) -> list[str]:
    if output is None:
        return ["（沒有工具回應）"]
    return [_fence(output)]


def _search_output(output: str | None) -> list[str]:
    """搜尋結果是 JSON 陣列 + 後面一句還剩幾次。認得出來就一筆一段，不然整段照印。"""
    if output is None:
        return _output(output)
    try:
        results, end = json.JSONDecoder().raw_decode(output)
    except json.JSONDecodeError:
        return _output(output)
    if not isinstance(results, list) or not all(
        isinstance(r, dict) and {"title", "url", "content"} <= r.keys() for r in results
    ):
        return _output(output)
    parts = []
    for i, r in enumerate(results, 1):
        parts += [f"### {i}. {r['title']}", r["url"], _fence(r["content"])]
    rest = output[end:].strip()
    if rest:
        parts.append(_fence(rest))
    return parts


def _fence(text: str) -> str:
    # 用比內容裡最長的一串 ` 還多一個的 ` 包起來，內容裡的 ``` 才不會把區塊提早關掉
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"
