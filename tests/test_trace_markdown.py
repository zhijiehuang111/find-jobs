"""trace 轉 Markdown：只加標題和排版，trace 裡的文字一個字都不能少、不能改。"""

import json

from company_research import ItemAnswer, Report
from company_research.trace import research_markdown, trace_markdown

TASK = "# 今天日期\n2030-01-02\n\n# 公司全名\n○○科技股份有限公司"
HIT = {
    "title": "[心得] ○○科技 面試",
    "url": "https://example.com/bbs/1",
    "content": "面試三關，\n第二關考 *系統設計*",
}
PAGE = "第一行\n```\n頁面裡本來就有的 code block\n```\n最後一行"
ANSWER = "一句話：做 △△ 物流管理 SaaS\n客戶：中小型電商"
REJECTED = (
    "報告沒通過檢查，修正後重新交：\n- news：來源網址 https://example.com/x 沒出現過"
)
SECRET = "gAAAA-encrypted-blob"


def call(call_id: str, name: str, **arguments: object) -> dict:
    return {
        "type": "function_call",
        "call_id": call_id,
        "name": name,
        "arguments": json.dumps(arguments, ensure_ascii=False),
    }


def output(call_id: str, text: str) -> dict:
    return {"type": "function_call_output", "call_id": call_id, "output": text}


def answer(key: str, text: str, sources: list[str]) -> dict:
    return {"key": key, "status": "found", "answer": text, "sources": sources}


TRACE = [
    {"role": "user", "content": TASK},
    {"type": "reasoning", "summary": [], "encrypted_content": SECRET},
    call("c1", "search", query="○○ 面試", sites=["example.com"]),
    call("c2", "read_page", url=HIT["url"]),
    output(
        "c1", json.dumps([HIT], ensure_ascii=False) + "\n\n（搜尋和讀網頁還剩 14 次）"
    ),
    output("c2", PAGE),
    {"type": "reasoning", "summary": [{"type": "summary_text", "text": "再補查新聞"}]},
    call(
        "c3", "submit_report", items=[answer("news", "亂寫", ["https://example.com/x"])]
    ),
    output("c3", REJECTED),
    call("c4", "submit_report", items=[answer("what_it_does", ANSWER, [HIT["url"]])]),
]


def test_all_text_in_trace_is_kept_as_is() -> None:
    md = trace_markdown("○○科技", TRACE)

    for text in [
        TASK,
        HIT["title"],
        HIT["url"],
        HIT["content"],
        "（搜尋和讀網頁還剩 14 次）",
        PAGE,
        "再補查新聞",
        REJECTED,
        ANSWER,
        "○○ 面試",
        "example.com",
    ]:
        assert text in md, text


def test_each_tool_call_gets_a_numbered_heading_in_order() -> None:
    md = trace_markdown("○○科技", TRACE)

    headings = [line for line in md.splitlines() if line.startswith("## #")]
    assert [h.split("：")[0].split("（")[0] for h in headings] == [
        "## #1 search",
        "## #2 read_page",
        "## #3 submit_report",
        "## #4 submit_report",
    ]


def test_tool_output_is_shown_right_after_its_call() -> None:
    # 平行呼叫時歷史裡是「呼叫、呼叫、回應、回應」，給人看的時候每個呼叫接著它的回應
    md = trace_markdown("○○科技", TRACE)

    assert md.index("## #1") < md.index(HIT["content"]) < md.index("## #2")
    assert md.index("## #2") < md.index(PAGE) < md.index("## #3")


def test_encrypted_reasoning_is_not_dumped() -> None:
    md = trace_markdown("○○科技", TRACE)

    assert SECRET not in md
    assert "加密" in md


def test_code_fence_in_content_does_not_end_the_block_early() -> None:
    # 頁面裡本來就有 ```，外面的區塊要用更長的 ```` 包，不然 Markdown 會在中間斷掉
    md = trace_markdown("○○科技", TRACE)

    start = md.index(PAGE)
    fence_line = md[: start - 1].rsplit("\n", 1)[-1]
    assert fence_line.startswith("````")


def report() -> Report:
    return Report(
        company="○○科技股份有限公司",
        items=[
            ItemAnswer(
                key="what_it_does",
                status="found",
                answer=ANSWER,
                sources=[HIT["url"]],
            ),
            ItemAnswer(key="news", status="not_found", answer="查不到", sources=[]),
        ],
        model="fake-model",
        tool_calls=4,
        input_tokens=123456,
        output_tokens=789,
        trace=TRACE,
    )


def test_final_report_and_cost_come_before_the_trace() -> None:
    # 打 pass/fail 看的是最終報告（前端那份），放最上面，不用跳到最後一個 submit_report
    md = research_markdown(report())

    final = md.index("## 最終報告")
    assert final < md.index(ANSWER) < md.index("## 任務")
    assert final < md.index("查不到") < md.index("## 任務")
    for text in ["fake-model", "4", "123456", "789"]:
        assert text in md[: md.index("## 任務")], text


def test_trace_is_still_complete_below_the_report() -> None:
    md = research_markdown(report())

    assert md.startswith("# ○○科技股份有限公司\n")
    assert trace_markdown("x", TRACE).split("\n", 1)[1] in md
