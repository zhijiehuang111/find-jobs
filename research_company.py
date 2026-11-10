"""
手動對一家公司跑一次公司調查，把調查報告印成 JSON。會打 OpenAI 和 Tavily（花錢）。
查的項目跟前端按鈕一樣（research_items.py）。

    uv run research_company.py "○○科技股份有限公司"
    uv run research_company.py "○○科技股份有限公司" --company-url https://www.104.com.tw/company/xxxxxxx
    uv run research_company.py "○○科技股份有限公司" --known "公司簡介…" https://example.com/profile
    uv run research_company.py "○○科技股份有限公司" --trace traces/○○   # 調查過程存成 ○○.json 和 ○○.md

需要 OPENAI_API_KEY、TAVILY_API_KEY；可選 RESEARCH_MODEL、RESEARCH_BASE_URL。
"""

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from company_research import KnownFact, research
from company_research.research import DEFAULT_MAX_TOOL_CALLS
from company_research.trace import trace_markdown
from research_items import company_profile, research_items


def main() -> None:
    parser = argparse.ArgumentParser(description="對一家公司跑一次公司調查")
    parser.add_argument("company", help="公司全名")
    parser.add_argument(
        "--company-url",
        metavar="URL",
        help="104 公司頁網址，像 https://www.104.com.tw/company/xxxxxxx"
        "（後面不要帶 ?jobsource 那些）。會跟按鈕一樣抓公司簡介當已知資料",
    )
    parser.add_argument(
        "--known",
        nargs=2,
        action="append",
        default=[],
        metavar=("CONTENT", "URL"),
        help="已知資料和它的來源網址，可以給多次",
    )
    parser.add_argument("--max-tool-calls", type=int, default=DEFAULT_MAX_TOOL_CALLS)
    parser.add_argument(
        "--trace",
        type=Path,
        metavar="FILE",
        help="把調查過程（送給模型的完整歷史）寫成 FILE.json（給程式讀）"
        "和 FILE.md（給人讀）。FILE 有沒有寫 .json 都可以",
    )
    args = parser.parse_args()
    # 調查跑完才寫檔，資料夾不存在的話錢就白花了，先檢查
    if args.trace and not args.trace.parent.is_dir():
        parser.error(f"--trace 的資料夾不存在：{args.trace.parent}")

    load_dotenv()
    # 調查過程印到 stderr，報告的 JSON 照樣印到 stdout
    logging.basicConfig(format="%(message)s")
    logging.getLogger("company_research").setLevel(logging.INFO)
    known = [KnownFact(content=c, source_url=u) for c, u in args.known]
    if args.company_url:
        profile = company_profile(args.company_url)
        # 按鈕抓不到會照常調查；CLI 是特地給了網址，抓不到多半是網址貼錯，
        # 不停下來的話會花錢跑出一份沒有 104 簡介的結果
        if not profile:
            parser.error(f"沒抓到 104 公司簡介，檢查網址：{args.company_url}")
        known += profile
    today = datetime.now().astimezone().date()
    report = research(
        args.company,
        research_items(today),
        known,
        max_tool_calls=args.max_tool_calls,
        today=today,
    )
    print(report.model_dump_json(indent=2))
    if args.trace:
        args.trace.with_suffix(".json").write_text(
            json.dumps(report.trace, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        args.trace.with_suffix(".md").write_text(
            trace_markdown(args.company, report.trace), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
