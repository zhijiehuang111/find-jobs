"""
公司調查的 agent loop：research() 是對外唯一的進入點。

不 import find-jobs 的任何東西、不碰 DB、不認識 104（ADR 0002）。

LLM 用 Responses API，但不用伺服器端的狀態（store=False、不用 previous_response_id），
每一輪都送完整的歷史，這樣 base_url 換成 Ollama 也能直接跑。
"""

import json
import logging
import os
from typing import Any, Literal

from openai import OpenAI, pydantic_function_tool
from openai.types.responses import FunctionToolParam
from pydantic import BaseModel, Field, ValidationError

from company_research.read_page import Reader, TavilyExtract
from company_research.search import Searcher, TavilySearch

# 調查過程每次工具呼叫印一行。這裡不設 handler，要不要印出來由呼叫端決定
log = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-6-luna"
DEFAULT_MAX_TOOL_CALLS = 20
# 一頁最多給模型看幾個字元。每一輪都重送完整歷史，讀過的頁面會一直被重送，
# 太長的頁面要截掉，不然 token 越疊越多、甚至超過 context window
MAX_PAGE_CHARS = 15_000


class ResearchItem(BaseModel):
    """調查項目：呼叫端想知道的一件事。"""

    key: str
    name: str
    question: str
    criteria: str  # 合格標準


class KnownFact(BaseModel):
    """已知資料：呼叫端調查前就有的資料，答案可以引用它的來源網址。"""

    content: str
    source_url: str


# docstring 和 Field 的 description 會進交報告工具的 schema，是寫給模型看的
class ItemAnswer(BaseModel):
    """一個調查項目的答案。"""

    key: str = Field(description="調查項目的 key")
    status: Literal["found", "not_found"]
    answer: str = Field(description="繁體中文的答案")
    sources: list[str] = Field(description="支持答案的來源網址")


class Report(BaseModel):
    """調查報告。items 由模型交，其他欄位由 loop 記下。"""

    company: str
    items: list[ItemAnswer]
    model: str
    tool_calls: int
    input_tokens: int
    output_tokens: int


class _SearchArgs(BaseModel):
    query: str = Field(description="搜尋關鍵字")


class _ReadPageArgs(BaseModel):
    url: str = Field(description="要讀的網頁網址")


class _SubmitReportArgs(BaseModel):
    items: list[ItemAnswer]


def _function_tool(
    args: type[BaseModel], name: str, description: str
) -> FunctionToolParam:
    """pydantic model -> Responses API 的 strict function tool。

    工具的 schema 和解析模型交回來的參數用同一個 model，兩邊不會對不上。
    pydantic_function_tool 產生的是 Chat Completions 的格式，這裡攤平成 Responses 的。
    """
    function = pydantic_function_tool(args, name=name, description=description)[
        "function"
    ]
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": dict(function.get("parameters", {})),
        "strict": True,
    }


INSTRUCTIONS = """\
你是公司調查員。使用者會給你一家公司的全名、要調查的項目，以及已知資料。
用 search 工具找相關的網頁，再用 read_page 工具讀網頁全文，
每個項目都查完之後，用 submit_report 工具交出調查報告。

- 搜尋結果只是片段，不能只看片段就下結論：要當成來源的網頁，都要先用 read_page 讀過全文。
- 答案一律用繁體中文。
- 每個項目的答案都要符合它的合格標準，並附上支持答案的來源網址。
- 來源網址只能用 read_page 讀過的網址，或已知資料的來源網址，不要自己編。
- 用到母公司、集團、品牌等關聯實體的資訊時，答案裡要標明是誰的，不要當成這家公司本身的事。
- 查不到是有效的答案：找不到符合合格標準的來源時，status 填 not_found、sources 留空，不要猜。
"""

TOOLS = [
    _function_tool(_SearchArgs, "search", "上網搜尋，回傳結果的標題、網址和內容片段。"),
    _function_tool(_ReadPageArgs, "read_page", "讀一個網頁的全文。"),
    _function_tool(
        _SubmitReportArgs, "submit_report", "交出調查報告。每個調查項目都要剛好一筆。"
    ),
]


def _task_text(company: str, items: list[ResearchItem], known: list[KnownFact]) -> str:
    lines = [f"# 公司全名\n{company}", "# 調查項目"]
    for item in items:
        lines.append(
            f"- key: {item.key}\n  名稱：{item.name}\n"
            f"  問題：{item.question}\n  合格標準：{item.criteria}"
        )
    lines.append("# 已知資料")
    if known:
        for fact in known:
            lines.append(f"- 來源：{fact.source_url}\n  {fact.content}")
    else:
        lines.append("（無）")
    return "\n\n".join(lines)


def _normalize_url(url: str) -> str:
    """比對來源網址前的最基本正規化：去掉 # 之後的部分和結尾的 /。"""
    return url.split("#", 1)[0].rstrip("/")


class _SeenUrls:
    """這次調查看過的網址。加進來和查詢都會先正規化，呼叫端不用管。"""

    def __init__(self) -> None:
        self._urls: set[str] = set()

    def add(self, *urls: str) -> None:
        self._urls.update(_normalize_url(url) for url in urls)

    def __contains__(self, url: str) -> bool:
        return _normalize_url(url) in self._urls


def _answer_errors(answer: ItemAnswer, seen_urls: _SeenUrls) -> list[str]:
    """一個項目的答案單獨看有哪些問題（不管 key 對不對）。"""
    errors = []
    if answer.status == "found" and not answer.sources:
        errors.append(f"{answer.key}：status 是 found，但沒有附來源網址")
    for url in answer.sources:
        if url not in seen_urls:
            errors.append(
                f"{answer.key}：來源網址 {url} 沒有出現在這次的工具回應或已知資料裡"
            )
    return errors


def _report_errors(
    answers: list[ItemAnswer], items: list[ResearchItem], seen_urls: _SeenUrls
) -> list[str]:
    """交上來的報告哪裡沒通過檢查，每個問題一句話；空的就是通過。"""
    errors = []
    expected = [item.key for item in items]
    submitted = [answer.key for answer in answers]
    for key in expected:
        if key not in submitted:
            errors.append(f"少了調查項目 {key}")
        elif submitted.count(key) > 1:
            errors.append(f"調查項目 {key} 出現了 {submitted.count(key)} 次，只能一次")
    for key in dict.fromkeys(submitted):
        if key not in expected:
            errors.append(f"{key} 不是這次的調查項目")
    for answer in answers:
        errors.extend(_answer_errors(answer, seen_urls))
    return errors


def _salvage(
    answers: list[ItemAnswer], items: list[ResearchItem], seen_urls: _SeenUrls
) -> list[ItemAnswer]:
    """沒交出通過的報告就到上限時用：每個項目只出現一次、單獨通過檢查的答案保留，
    其他（沒答、答了好幾次、沒通過）都改成查不到。"""
    salvaged = []
    for item in items:
        matches = [a for a in answers if a.key == item.key]
        if len(matches) == 1 and not _answer_errors(matches[0], seen_urls):
            salvaged.append(matches[0])
        else:
            salvaged.append(
                ItemAnswer(key=item.key, status="not_found", answer="", sources=[])
            )
    return salvaged


def _cut_page(content: str) -> str:
    if len(content) <= MAX_PAGE_CHARS:
        return content
    return (
        content[:MAX_PAGE_CHARS]
        + f"\n\n（原文共 {len(content)} 字，只給前 {MAX_PAGE_CHARS} 字，後面截掉了）"
    )


def _default_client() -> OpenAI:
    # base_url 沒設就是 OpenAI；要換 Ollama 時設 RESEARCH_BASE_URL
    return OpenAI(base_url=os.getenv("RESEARCH_BASE_URL") or None)


def research(
    company: str,
    items: list[ResearchItem],
    known: list[KnownFact],
    *,
    client: OpenAI | None = None,
    searcher: Searcher | None = None,
    reader: Reader | None = None,
    model: str | None = None,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
) -> Report:
    """對一家公司跑一次公司調查，交出調查報告。

    OpenAI 呼叫失敗時直接拋出例外，由呼叫端處理。
    """
    client = client or _default_client()
    searcher = searcher or TavilySearch()
    reader = reader or TavilyExtract()
    model = model or os.getenv("RESEARCH_MODEL") or DEFAULT_MODEL

    history: list[Any] = [
        {"role": "user", "content": _task_text(company, items, known)}
    ]
    tool_calls = input_tokens = output_tokens = 0
    # 交報告的來源只能從這次調查看過的網址裡挑
    seen_urls = _SeenUrls()
    seen_urls.add(*(fact.source_url for fact in known))
    last_submitted: list[ItemAnswer] = []  # 最後一次交、被退回的報告

    def report(answers: list[ItemAnswer]) -> Report:
        return Report(
            company=company,
            items=answers,
            model=model,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    log.info(
        "[%s] ===== 開始調查：%d 個項目，工具呼叫上限 %d 次 =====",
        company,
        len(items),
        max_tool_calls,
    )
    while tool_calls < max_tool_calls:
        response = client.responses.create(
            model=model,
            instructions=INSTRUCTIONS,
            input=history,
            tools=TOOLS,
            tool_choice="required",
            store=False,
        )
        if response.usage:
            input_tokens += response.usage.input_tokens
            output_tokens += response.usage.output_tokens
        history.extend(response.output)

        calls = [o for o in response.output if o.type == "function_call"]
        if not calls:
            raise RuntimeError("模型沒有呼叫任何工具")

        for fc in calls:
            if tool_calls >= max_tool_calls:
                break
            tool_calls += 1

            try:
                if fc.name == "submit_report":
                    submitted = _SubmitReportArgs.model_validate_json(fc.arguments)
                    errors = _report_errors(submitted.items, items, seen_urls)
                    if not errors:
                        log.info("[%s] #%d submit_report: 通過", company, tool_calls)
                        return report(submitted.items)
                    last_submitted = submitted.items
                    output = "報告沒通過檢查，修正後重新交：\n" + "\n".join(
                        f"- {e}" for e in errors
                    )
                    summary = "退回：" + "；".join(errors)
                elif fc.name == "search":
                    query = _SearchArgs.model_validate_json(fc.arguments).query
                    try:
                        results = searcher.search(query)
                    except Exception as e:  # noqa: BLE001  網路、額度、rate limit 都算
                        # 搜尋失敗交給模型決定要不要重試；OpenAI 的失敗才往外拋
                        output = f"搜尋失敗：{type(e).__name__}: {e}"
                        summary = f"{query} → {output}"
                    else:
                        seen_urls.add(*(r.url for r in results))
                        output = json.dumps(
                            [r.model_dump() for r in results], ensure_ascii=False
                        )
                        summary = f"{query} → {len(results)} 筆"
                elif fc.name == "read_page":
                    url = _ReadPageArgs.model_validate_json(fc.arguments).url
                    try:
                        page = reader.read(url)
                    except Exception as e:  # noqa: BLE001  404、被擋、逾時都算
                        output = f"讀網頁失敗：{type(e).__name__}: {e}"
                        summary = f"{url} → {output}"
                    else:
                        seen_urls.add(url)
                        output = _cut_page(page.content)
                        summary = f"{url} → {len(page.content)} 字"
                else:
                    output = f"沒有這個工具：{fc.name}"
                    summary = output
            except ValidationError as e:
                output = f"參數格式錯誤：{e}"
                summary = "參數格式錯誤"

            log.info("[%s] #%d %s: %s", company, tool_calls, fc.name, summary)

            history.append(
                {
                    "type": "function_call_output",
                    "call_id": fc.call_id,
                    "output": output,
                }
            )

    # 用完工具呼叫次數還沒交出通過的報告：從最後一次交的報告裡留下通過的項目，
    # 完全沒交過就全部查不到
    log.info(
        "[%s] 用完 %d 次工具呼叫的上限結束，%s",
        company,
        max_tool_calls,
        "最後一次交的報告被退回" if last_submitted else "沒交過報告",
    )
    return report(_salvage(last_submitted, items, seen_urls))
