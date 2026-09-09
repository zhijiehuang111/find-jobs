# frontend

find-jobs 的前端。Vite + React + TypeScript + Tailwind v4，單頁四個 tab，沒有路由。

風格與互動的決定在根目錄的 `FRONTEND.md`，那份沒定、由這邊補的決定在 `design-notes.md`。

## 開發

要開兩個 process：

    uv run fastapi dev api.py    # 在 repo 根目錄，8000
    npm run dev                  # 在這裡，5173

Vite 的 `server.proxy` 把 `/api` 轉到 8000，同 origin，不用處理 CORS。

## 正式

    npm run build

出 `dist/`，交給 nginx 直接送；`/api/` 由 nginx `proxy_pass` 到 `127.0.0.1:8000`。
見根目錄的 `DEPLOY.md`。
