"""
公司調查：直接呼叫 research()，LLM 和搜尋都用假的，不打任何 API。

假 LLM 照劇本依序回應：每一輪回傳劇本裡的下一組工具呼叫。
"""

import json
from types import SimpleNamespace
from typing import Any, cast

from openai import OpenAI
from openai.types.responses import ResponseFunctionToolCall

from company_research import (
    ItemAnswer,
    KnownFact,
    Report,
    ResearchItem,
    SearchResult,
    research,
)

COMPANY = "○○科技股份有限公司"
WHAT_IT_DOES = ResearchItem(
    key="what_it_does",
    name="在做什麼",
    question="這家公司的產品或服務是什麼？",
    criteria="要具體到產品名稱或服務內容",
)
FAKE_URL = "https://example.com/oo-tech"


def call(name: str, **arguments: Any) -> ResponseFunctionToolCall:
    """模型的一次工具呼叫。call_id 用工具名 + 參數，劇本裡不用自己編號。"""
    args = json.dumps(arguments, ensure_ascii=False)
    return ResponseFunctionToolCall(
        type="function_call", call_id=f"{name}:{args}", name=name, arguments=args
    )


def submit(*answers: dict) -> ResponseFunctionToolCall:
    return call("submit_report", items=list(answers))


class ScriptedLLM:
    """照劇本回應的假 OpenAI client，記下每一輪送了什麼。"""

    def __init__(self, *turns: list[ResponseFunctionToolCall]) -> None:
        self.turns = list(turns)
        self.requests: list[dict] = []
        self.responses = self  # 讓 client.responses.create 打到這裡

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append({**kwargs, "input": list(kwargs["input"])})
        return SimpleNamespace(
            output=self.turns.pop(0),
            usage=SimpleNamespace(input_tokens=100, output_tokens=10),
        )

    def as_client(self) -> OpenAI:
        return cast(OpenAI, self)


class FakeSearch:
    """每次搜尋都回同一組結果，記下查了什麼。"""

    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.queries: list[str] = []

    def search(self, query: str) -> list[SearchResult]:
        self.queries.append(query)
        return self.results


def test_search_then_submit_returns_report() -> None:
    llm = ScriptedLLM(
        [call("search", query="○○科技 產品")],
        [
            submit(
                {
                    "key": "what_it_does",
                    "status": "found",
                    "answer": "做 △△ 物流管理 SaaS，客戶是中小型電商",
                    "sources": [FAKE_URL],
                }
            )
        ],
    )
    search = FakeSearch(
        [SearchResult(title="○○科技", url=FAKE_URL, content="△△ 物流管理 SaaS")]
    )

    report = research(
        COMPANY,
        [WHAT_IT_DOES],
        [],
        client=llm.as_client(),
        searcher=search,
        model="fake-model",
    )

    assert search.queries == ["○○科技 產品"]
    assert report == Report(
        company=COMPANY,
        items=[
            ItemAnswer(
                key="what_it_does",
                status="found",
                answer="做 △△ 物流管理 SaaS，客戶是中小型電商",
                sources=[FAKE_URL],
            )
        ],
        model="fake-model",
        tool_calls=2,
        input_tokens=200,
        output_tokens=20,
    )


def test_each_turn_sends_full_history() -> None:
    # 不用伺服器端狀態，所以第二輪要自己帶上：原本的輸入、模型的呼叫、工具的回應
    search_call = call("search", query="○○科技 產品")
    llm = ScriptedLLM([search_call], [submit()])
    search = FakeSearch(
        [SearchResult(title="○○科技", url=FAKE_URL, content="△△ 物流管理 SaaS")]
    )

    research(COMPANY, [WHAT_IT_DOES], [], client=llm.as_client(), searcher=search)

    first, second = (r["input"] for r in llm.requests)
    assert second[: len(first)] == first
    assert second[len(first)] == search_call
    tool_output = second[len(first) + 1]
    assert tool_output["type"] == "function_call_output"
    assert tool_output["call_id"] == search_call.call_id
    assert [r["url"] for r in json.loads(tool_output["output"])] == [FAKE_URL]


def test_known_facts_are_sent_to_model() -> None:
    llm = ScriptedLLM([submit()])
    known = KnownFact(
        content="本公司專營 △△ 物流管理 SaaS", source_url="https://example.com/profile"
    )

    research(
        COMPANY,
        [WHAT_IT_DOES],
        [known],
        client=llm.as_client(),
        searcher=FakeSearch([]),
    )

    sent = json.dumps(llm.requests[0]["input"], ensure_ascii=False)
    assert known.content in sent
    assert known.source_url in sent


def test_stops_at_tool_call_limit_with_all_not_found() -> None:
    # 一輪平行呼叫兩次搜尋，上限 3：第二輪的第二次不會執行
    llm = ScriptedLLM(
        [call("search", query="甲"), call("search", query="乙")],
        [call("search", query="丙"), call("search", query="丁")],
        [submit()],
    )
    search = FakeSearch([])

    report = research(
        COMPANY,
        [WHAT_IT_DOES],
        [],
        client=llm.as_client(),
        searcher=search,
        max_tool_calls=3,
    )

    assert search.queries == ["甲", "乙", "丙"]
    assert len(llm.requests) == 2
    assert report.tool_calls == 3
    assert report.items == [
        ItemAnswer(key="what_it_does", status="not_found", answer="", sources=[])
    ]
