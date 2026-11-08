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
        response = self.client.extract(urls=[url], format="markdown")
        if not response["results"]:
            errors = [f["error"] for f in response["failed_results"]]
            raise RuntimeError(f"讀不到 {url}：{'；'.join(errors) or '沒有回傳內容'}")
        result = response["results"][0]
        return Page(url=result["url"], content=result["raw_content"])
