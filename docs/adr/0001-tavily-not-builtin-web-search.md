# 公司調查的搜尋用 Tavily，不用 LLM API 內建的 web search

公司調查的搜尋和讀網頁用 Tavily 包成我們自己的工具，不用 OpenAI Responses API 內建的 `web_search`。內建的比較省事，但搜尋在 OpenAI 那邊發生，只回傳搜尋關鍵字和參考過的網址，拿不到模型實際讀到的內容。這樣沒辦法用 code 確認報告寫的東西真的出自那些網頁，事後自己抓的不一定是模型當時讀的那份。eval 也沒辦法固定搜尋結果，每跑一次都重新上網查，分數變了分不出是 prompt 的影響還是網路內容變了。用自己的工具，就能把 Tavily 的回應存下來重複使用。

## Consequences

- eval 存下來的搜尋結果是 Tavily 回應的格式，之後換搜尋服務，這些存檔就要重新產生。
- 搜尋要做成可以替換的 function，loop 不直接呼叫 Tavily 的 SDK。
