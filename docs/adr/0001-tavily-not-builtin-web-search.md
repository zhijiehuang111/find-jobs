# 公司調查的搜尋用 Tavily，不用 LLM API 內建的 web search

公司調查的搜尋和讀網頁用 Tavily 包成我們自己的工具，不用 OpenAI Responses API 內建的 `web_search`。內建的設定比較省事，但搜尋是在 OpenAI 那邊發生的：我們看不到它查了什麼、讀了哪些頁面，也就沒辦法用 code 檢查報告裡的網址是不是真的出現過，更沒辦法把 Tavily 的回應存下來，讓 eval 重複使用、不用每次都打 API。另外，之後如果費用太高要換成 Ollama 跑本地模型，用內建搜尋的話這一整塊都要重寫。

## Consequences

- eval 存下來的搜尋結果是 Tavily 回應的格式，之後換搜尋服務，這些存檔就要重新產生。
- 搜尋要做成可以替換的 function，loop 不直接呼叫 Tavily 的 SDK。
