# find-jobs

每天抓 104 職缺 → LLM 依 profile 判斷適不適合 → 存 Postgres → 前端分 tab 看、人工標註。
流程圖、eval 成績、設計決定見 README，這裡只寫開發時要知道的。

## 檔案地圖

| 檔案 | 角色 |
|---|---|
| `fetch_104.py` | 104 API 存取（search / detail / 公司簡介 / 重試）。沒有進入點，只被 import |
| `judge.py` | JD 攤平成文字 + 呼叫 OpenAI 判 fit/reason。沒有進入點 |
| `pipeline.py` | 每日主流程：列表 → 去重 → 黑名單 → 薪資 → detail → LLM → DB |
| `run_daily.sh` | cron 呼叫，跑 3 個關鍵字的 pipeline，log 寫 `logs/` |
| `rejudge.py` | 改 prompt/profile 後重判還沒標的，讀 DB 的 `raw_detail`，不打 104 |
| `prune_closed.py` | 收件匣裡已下架的職缺刪掉 |
| `build_dataset.py` / `eval.py` | 考卷（`labels.tsv` → `dataset.jsonl`）和評分 |
| `api.py` + `queries.py` | FastAPI；SQL 全部在 `queries.py`，回傳一律 dict |
| `company_research/` | 公司調查：`research()` 是唯一對外的 function，不 import find-jobs（ADR 0002）。沒有進入點，只被 import |
| `research_items.py` | find-jobs 要查的調查項目和合格標準，起始日每次調查時算。`api.py` 和 `research_company.py` 共用 |
| `research_company.py` | `uv run research_company.py "公司全名"` 手動跑一次公司調查，查的跟前端按鈕一樣 |
| `db.py` | `.env` → 連線字串，`api.py`（pool）和 `pipeline.connect()`（單條）共用 |
| `frontend/` | React + TS + Tailwind，dev 時 `/api` proxy 到 :8000 |
| `find_jobs.sql` | 完整的最新 schema（新建 DB 用） |
| `migrations/` | 已上線 DB 的變更，`00N_描述.sql` |

`private/` 是另一個 repo（find-jobs-private），gitignore 掉了：
`prompts/rules.md`、`profile.md`、`filters.py`（黑名單、薪資門檻）、`labels.tsv`、`dataset.jsonl`、`evals/`。
CI 上沒有它，所以測試不能 import `private`。測試要用規則或門檻時，自己編一看就是假的值，不要照抄 `private/` 的真實設定（這個 repo 是公開的）。

## 常用指令

```bash
docker compose up -d                 # 起 Postgres（.env 要有 POSTGRES_*）
docker compose up -d postgres-test   # 測試用 DB（:55432，資料在記憶體），pytest 要它
uv run fastapi dev api.py            # API，http://127.0.0.1:8000/docs
cd frontend && npm run dev           # 前端
uv run ruff check . && uv run ruff format --check . && uv run pytest   # 跟 CI 一樣
uvx pyright --pythonpath .venv/bin/python *.py tests                   # 型別檢查，跟 VS Code 的 Pylance 同引擎
cd frontend && npm run lint && npm run build                           # 前端 CI
```

## 會花錢 / 有副作用的

- **打 OpenAI（花錢）**：`pipeline.py`、`rejudge.py`、`eval.py`、`research_company.py`
- **打 Tavily（花錢）**：`research_company.py`
- **打 104 API**：`pipeline.py`、`prune_closed.py`、`build_dataset.py`、`api.py` 的「調查公司」（抓公司簡介）
- **寫 DB**：`pipeline.py`、`rejudge.py`、`prune_closed.py --apply`
- 先看範圍再跑：`rejudge.py --dry-run`、`prune_closed.py`（不加 `--apply` 只列出）、`eval.py 10`（只跑 10 題）

## 改東西時的約定

- **改 Python**：改完跑 ruff 和 pyright，兩個都要 0 error。pyright 不在 CI 裡，要自己跑。
- **改 prompt / profile**：先跑 `eval.py` 確認分數，OK 了再跑 `rejudge.py`。
  改完記得 push `private/`，不然 VPS 部署 pull 到的是舊的。
- **換考卷**（加題、改答案）：先用當前版本重跑一次 eval 當新基準線，分數只有 dataset hash 相同才能比。
- **改 schema**：`find_jobs.sql` 和新的 `migrations/00N_*.sql` 都要改。只動資料的 migration 不用改 `find_jobs.sql`。
- **改 API / SQL**：`tests/test_api.py` 打真的 Postgres，不要 mock `queries`。連線寫死在 `tests/conftest.py`、不讀 `.env`，別改成讀 `.env`，測試會 `TRUNCATE jobs`。
- **main 不能直接 push**：任何改動都先開 branch，走 PR merge（merge 進 main 就會自動部署）。
- PR 標題用 `feat:` / `fix:` / `ci:` / `chore:`，squash 後會變成 commit 訊息。

## 部署

push 到 main → CI（ruff、pytest、前端 build）→ ssh 進 VPS pull 兩個 repo、build、restart、health check。
VPS 設定細節在本機的 `DEPLOY.md`（不進 git）。

**CI 不會跑 migration，要手動在 VPS 上跑。**
只加東西（加欄位、加表）的在 merge 前跑；改型別、改名、刪欄位的在 merge 部署完後馬上跑。

## 地雷

- 讀 `dataset.jsonl` 要用 `split("\n")`，不能用 `splitlines()`：JD 裡有 U+2028，會把一行 JSON 切斷。

## Agent skills

### Issue tracker

Issue 放在 GitHub Issues（公開 repo），用 `gh` 操作；不寫 `private/` 的內容，開之前先給使用者看草稿。See `docs/agents/issue-tracker.md`.

### Triage labels

用預設的 5 個 label：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。See `docs/agents/triage-labels.md`.

### Domain docs

Single-context：根目錄一個 `GLOSSARY.md` + `docs/adr/`（用到才建）。See `docs/agents/domain.md`.
