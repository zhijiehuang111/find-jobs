# find-jobs

個人使用的小工具：每天自動根據特定關鍵字抓 104 職缺，用 LLM 依我的 profile 判斷適不適合投，結果存進 Postgres，前端根據判斷的結果分成不同的 tab 顯示職缺

## 介面

![介面](docs/image.png)

## 流程

```mermaid
flowchart TB
  cron[cron 每天 10:00] --> list["104 search API<br/>4 關鍵字 × 相關度/最近更新 × 2 頁<br/>jobcat + 地區, slug 去重"]
  list --> seen{DB 已有?}
  seen -->|是| skip1[跳過, 不花錢]
  seen -->|否| block{職稱/公司黑名單}
  block -->|擋掉| skip2[只進 log, 不寫 DB]
  block -->|通過| sal{薪資門檻}
  sal -->|刷掉| rej[("list_rejected<br/>留 raw_list")]
  sal -->|通過| detail[104 detail API]
  detail --> llm["LLM judge<br/>rules + profile + JD<br/>→ fit / reason"]
  llm --> db[("Postgres<br/>raw JSON, fit, reason<br/>prompt/profile hash, model")]
  rej --> db
  db -->|關鍵字都跑完| prune["清掉已下架<br/>收件匣重抓 104 detail, 下架的刪掉<br/>標過 / 收藏的不動"]
  prune -->|刪除| db
  db --> api[FastAPI] --> ui["前端 4 tabs<br/>收件匣 / 收藏 / 不適合 / 規則刷掉"]
  ui -->|human_label + 理由| db
  db -. 挑題 .-> exam[固定考卷 100 題]
  exam -. 離線跑同一套 judge, 不寫 DB .-> eval["eval: accuracy / precision / recall"]
  eval -. 新版 OK, 手動跑 .-> rejudge["rejudge.py<br/>讀 raw_detail 重判還沒標的, 不打 104 API"] -.-> db
```

## Tech Stack

Python｜FastAPI + psycopg｜Postgres 18  
React + TypeScript + Tailwind｜OpenAI Responses API

跑在自己的 VPS：Docker Postgres、cron、systemd + nginx basic auth + TLS

## Eval

目前 100 筆固定職缺 ＋ 我標註的答案，存成 `dataset.jsonl` 用 git 管，每一版 prompt 都跑同一份

每次跑 `eval.py` 的結果附一行到 `history.tsv`，記下 prompt / profile / dataset 的內容 hash 和 model 名稱，分數才知道能不能互相比。
