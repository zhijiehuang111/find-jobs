"""
讀網頁的介面和 Tavily 實作。

跟 Searcher 一樣，loop 只認 Reader，不直接碰 Tavily SDK（ADR 0001）。
"""

from typing import Protocol

from pydantic import BaseModel
from tavily import TavilyClient


class Page(BaseModel):
    url: str
    content: str


class Reader(Protocol):
    def read(self, url: str) -> Page: ...


class TavilyExtract:
    """Tavily extract。API key 由 TavilyClient 自己讀 TAVILY_API_KEY。"""

    def __init__(self) -> None:
        self.client = TavilyClient()

    def read(self, url: str) -> Page:
        # text 大約只有 markdown 的 1/3：markdown 多出來的大多是導覽列的連結網址，
        # 模型用不到（只有讀過的網址能當來源）
        response = self.client.extract(urls=[url], format="text")
        if not response["results"]:
            errors = [f["error"] for f in response["failed_results"]]
            raise RuntimeError(f"讀不到 {url}：{'；'.join(errors) or '沒有回傳內容'}")
        result = response["results"][0]
        return Page(url=result["url"], content=result["raw_content"])
