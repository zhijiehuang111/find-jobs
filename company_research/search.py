"""
搜尋的介面和 Tavily 實作。

loop 只認 Searcher，不直接碰 Tavily SDK（ADR 0001），測試和 eval 可以換成假的或讀存檔的版本。
"""

from typing import Protocol

from pydantic import BaseModel
from tavily import TavilyClient


class SearchResult(BaseModel):
    title: str
    url: str
    content: str


class Searcher(Protocol):
    def search(self, query: str, sites: list[str]) -> list[SearchResult]:
        """sites 是空的就不限定網站。"""
        ...


class TavilySearch:
    """Tavily search。API key 由 TavilyClient 自己讀 TAVILY_API_KEY。"""

    def __init__(self) -> None:
        self.client = TavilyClient()

    def search(self, query: str, sites: list[str]) -> list[SearchResult]:
        if sites:
            response = self.client.search(query, include_domains=sites)
        else:
            response = self.client.search(query)
        return [
            SearchResult(title=r["title"], url=r["url"], content=r["content"])
            for r in response["results"]
        ]
