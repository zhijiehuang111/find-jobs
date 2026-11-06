"""
手動對一家公司跑一次公司調查，把調查報告印成 JSON。會打 OpenAI 和 Tavily（花錢）。

    uv run -m company_research "○○科技股份有限公司"
    uv run -m company_research "○○科技股份有限公司" --known "公司簡介…" https://example.com/profile

需要 OPENAI_API_KEY、TAVILY_API_KEY；可選 RESEARCH_MODEL、RESEARCH_BASE_URL。
"""

import argparse

from dotenv import load_dotenv

from company_research import KnownFact, ResearchItem, research
from company_research.research import DEFAULT_MAX_TOOL_CALLS

# 這張先只查一個項目，內容照 #11 的「在做什麼」
WHAT_IT_DOES = ResearchItem(
    key="what_it_does",
    name="在做什麼",
    question="這家公司的產品或服務是什麼？客戶是誰？怎麼賺錢？",
    criteria=(
        "要具體到產品名稱或服務內容，只寫產業類別不算；"
        "代工或接案的公司要說出主要客戶的類型。"
    ),
)


def main() -> None:
    parser = argparse.ArgumentParser(description="對一家公司跑一次公司調查")
    parser.add_argument("company", help="公司全名")
    parser.add_argument(
        "--known",
        nargs=2,
        action="append",
        default=[],
        metavar=("CONTENT", "URL"),
        help="已知資料和它的來源網址，可以給多次",
    )
    parser.add_argument("--max-tool-calls", type=int, default=DEFAULT_MAX_TOOL_CALLS)
    args = parser.parse_args()

    load_dotenv()
    known = [KnownFact(content=c, source_url=u) for c, u in args.known]
    report = research(
        args.company, [WHAT_IT_DOES], known, max_tool_calls=args.max_tool_calls
    )
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
