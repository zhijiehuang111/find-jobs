"""
手動對一家公司跑一次公司調查，把調查報告印成 JSON。會打 OpenAI 和 Tavily（花錢）。
查的項目跟前端按鈕一樣（research_items.py）。

    uv run research_company.py "○○科技股份有限公司"
    uv run research_company.py "○○科技股份有限公司" --known "公司簡介…" https://example.com/profile

需要 OPENAI_API_KEY、TAVILY_API_KEY；可選 RESEARCH_MODEL、RESEARCH_BASE_URL。
"""

import argparse
import logging
from datetime import datetime

from dotenv import load_dotenv

from company_research import KnownFact, research
from company_research.research import DEFAULT_MAX_TOOL_CALLS
from research_items import research_items


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
    # 調查過程印到 stderr，報告的 JSON 照樣印到 stdout
    logging.basicConfig(format="%(message)s")
    logging.getLogger("company_research").setLevel(logging.INFO)
    known = [KnownFact(content=c, source_url=u) for c, u in args.known]
    today = datetime.now().astimezone().date()
    report = research(
        args.company,
        research_items(today),
        known,
        max_tool_calls=args.max_tool_calls,
        today=today,
    )
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
