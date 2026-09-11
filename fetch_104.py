"""
104 API 的存取層。

**沒有進入點**，只被 import：

    pipeline.py      -> search / fetch_detail / DROP_FIELDS / SLEEP_SECONDS
    build_dataset.py -> fetch_detail / DROP_FIELDS / SLEEP_SECONDS
"""

import json
import time

import httpx

SEARCH_API = "https://www.104.com.tw/jobs/search/api/jobs"
DETAIL_API = "https://www.104.com.tw/api/jobs/{slug}"

HEADERS = {
    "User-Agent": "find-jobs-bot/1.0 (personal job search)",
    "Referer": "https://www.104.com.tw/",
}

# 15 = 符合度高優先，16 = 最近更新。
ORDER_RELEVANCE = "15"
ORDER_LATEST = "16"

# 台北市 / 新北市 / 桃園市 / 新竹市
AREAS = "6001001000,6001002000,6001005000,6001006000"

# 軟體／工程類 + MIS／網管類
JOBCAT = "2007001000,2007002000"

SLEEP_SECONDS = 1.5  # 每次請求之間的間隔，別打太快
MAX_RETRIES = 3

# 存檔前丟掉的欄位。只丟「圖片和可重建的連結」這種確定是雜訊的，佔了原始資料約 1/4。
DROP_FIELDS = {
    "environmentPic",
    "reportUrl",
    "corpImageRight",
}


def get(url: str, params: dict | None = None, label: str = "") -> dict:
    """打一次 API。失敗就重試，連續失敗才拋出。"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = httpx.get(url, params=params, headers=HEADERS, timeout=20)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as err:
            if attempt == MAX_RETRIES:
                raise
            wait = SLEEP_SECONDS * 2**attempt
            print(f"  {label} 失敗 （{type(err).__name__}），{wait:.0f} 秒後重試")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def search(
    keyword: str, order: str = ORDER_LATEST, page: int = 1, pagesize: int = 20
) -> dict:
    """搜尋列表。只拿來取得職缺網址，內容不存。"""
    params = {
        "keyword": keyword,
        "order": order,
        "area": AREAS,
        "jobcat": JOBCAT,
        "page": page,
        "pagesize": pagesize,
    }
    return get(SEARCH_API, params, label=f"第 {page} 頁")


def fetch_detail(slug: str) -> dict:
    """單一職缺的完整內容：JD 全文、條件要求、其他條件。"""
    return get(DETAIL_API.format(slug=slug), label=f"職缺 {slug}")
