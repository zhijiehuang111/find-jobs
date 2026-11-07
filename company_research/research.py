"""
公司調查的 agent loop：research() 是對外唯一的進入點。

不 import find-jobs 的任何東西、不碰 DB、不認識 104（ADR 0002）。

LLM 用 Responses API，但不用伺服器端的狀態（store=False、不用 previous_response_id），
每一輪都送完整的歷史，這樣 base_url 換成 Ollama 也能直接跑。
"""

import json
import os
from typing import Any, Literal

from openai import OpenAI, pydantic_function_tool
from openai.types.responses import FunctionToolParam
from pydantic import BaseModel, Field, ValidationError

from company_research.search import Searcher, TavilySearch

DEFAULT_MODEL = "gpt-6-luna"
DEFAULT_MAX_TOOL_CALLS = 20


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
用 search 工具上網查，每個項目都查完之後，用 submit_report 工具交出調查報告。

- 答案一律用繁體中文。
- 每個項目的答案都要符合它的合格標準，並附上支持答案的來源網址。
- 來源網址只能用搜尋結果裡出現過的網址，或已知資料的來源網址，不要自己編。
- 用到母公司、集團、品牌等關聯實體的資訊時，答案裡要標明是誰的，不要當成這家公司本身的事。
- 查不到是有效的答案：找不到符合合格標準的來源時，status 填 not_found、sources 留空，不要猜。
"""

TOOLS = [
    _function_tool(_SearchArgs, "search", "上網搜尋，回傳結果的標題、網址和內容片段。"),
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


def _report_errors(
    answers: list[ItemAnswer], items: list[ResearchItem], seen_urls: set[str]
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
        if answer.status == "found" and not answer.sources:
            errors.append(f"{answer.key}：status 是 found，但沒有附來源網址")
        for url in answer.sources:
            if _normalize_url(url) not in seen_urls:
                errors.append(
                    f"{answer.key}：來源網址 {url} 沒有出現在這次的工具回應或已知資料裡"
                )
    return errors


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
    model: str | None = None,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
) -> Report:
    """對一家公司跑一次公司調查，交出調查報告。

    OpenAI 呼叫失敗時直接拋出例外，由呼叫端處理。
    """
    client = client or _default_client()
    searcher = searcher or TavilySearch()
    model = model or os.getenv("RESEARCH_MODEL") or DEFAULT_MODEL

    history: list[Any] = [
        {"role": "user", "content": _task_text(company, items, known)}
    ]
    tool_calls = input_tokens = output_tokens = 0
    # 這次調查看過的網址（正規化後），交報告的來源只能從這裡挑
    seen_urls = {_normalize_url(fact.source_url) for fact in known}

    def report(answers: list[ItemAnswer]) -> Report:
        return Report(
            company=company,
            items=answers,
            model=model,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
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
                        return report(submitted.items)
                    output = "報告沒通過檢查，修正後重新交：\n" + "\n".join(
                        f"- {e}" for e in errors
                    )
                elif fc.name == "search":
                    query = _SearchArgs.model_validate_json(fc.arguments).query
                    results = searcher.search(query)
                    seen_urls.update(_normalize_url(r.url) for r in results)
                    output = json.dumps(
                        [r.model_dump() for r in results], ensure_ascii=False
                    )
                else:
                    output = f"沒有這個工具：{fc.name}"
            except ValidationError as e:
                output = f"參數格式錯誤：{e}"

            history.append(
                {
                    "type": "function_call_output",
                    "call_id": fc.call_id,
                    "output": output,
                }
            )

    # 用完工具呼叫次數還沒交報告：全部當查不到
    return report(
        [
            ItemAnswer(key=item.key, status="not_found", answer="", sources=[])
            for item in items
        ]
    )
