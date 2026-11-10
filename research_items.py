"""
find-jobs 交給公司調查的東西：查哪幾項、合格標準是什麼，和當成已知資料的 104 公司簡介。

寫在呼叫端這邊，公司調查模組不認識它們（ADR 0002）。
api.py 的按鈕和 research_company.py 的 CLI 都用這份，兩邊給模型的資料一樣。
"""

import logging
from datetime import date

from company_research import KnownFact, ResearchItem
from fetch_104 import fetch_company

log = logging.getLogger(__name__)


def research_items(today: date) -> list[ResearchItem]:
    """今天要查的調查項目。

    「一年內」「三年內」的起始日在這裡用程式算好，模型只要比日期，不用自己算。
    以年為單位放寬：近期動向從去年 1/1 起，員工評價從三年前的 1/1 起。
    不能做成常數：API 一跑好幾個月，常數會停在啟動那天。
    """
    news_since = date(today.year - 1, 1, 1).isoformat()
    reviews_since = date(today.year - 3, 1, 1).isoformat()
    return [
        ResearchItem(
            key="what_it_does",
            name="在做什麼",
            question="這家公司賣什麼、賣給誰、怎麼賺錢？",
            criteria=(
                "用沒有這個產業背景的人也看得懂的白話寫，專有名詞要順便解釋。"
                "固定分三行：「一句話」不超過 40 字，說清楚賣什麼給誰；"
                "「客戶」說主要客戶的類型，代工或接案的公司要說是哪一類客戶；"
                "「怎麼賺錢」說主要收入來源，例如賣產品、訂閱、專案、代工。"
                "總共不超過 150 字，不列產品清單，不寫沿革和願景。"
            ),
        ),
        ResearchItem(
            key="recent_news",
            name="近期動向",
            question="這家公司最近有哪些看得出營運狀況的消息？",
            criteria=(
                f"只收 {news_since} 以後、主角是這家公司或標明的關聯實體的消息，"
                "類型限：營收或獲利的變化；募資、併購、上市櫃；"
                "裁員、組織調整或大量擴編；重大合作或主力產品上市。"
                "得獎、公益、行銷活動、徵才廣告不算。"
                "最多 3 則，挑最能看出公司現在好不好的，每則一句話，附日期和來源。"
            ),
        ),
        ResearchItem(
            key="employee_reviews",
            name="員工評價",
            question="在 PTT 上，員工、前員工或面試者怎麼評價這家公司？",
            criteria=(
                "只用 PTT：search 的 sites 填 ptt.cc，"
                "用一般人稱呼這家公司的簡稱搜「簡稱 工作」「簡稱 面試」。"
                f"只收 {reviews_since} 以後發的文章，要用 read_page 讀全文，推文也算。"
                "整理成重點，有寫到才列：薪資、工時加班、團隊氛圍和管理、面試流程；"
                "每點附發文日期，發文者有寫職位的話也標出來。"
                "公司自己寫的福利介紹和徵才文案不算；搜 2 次沒找到就回報查不到。"
            ),
        ),
    ]


# 104 公司簡介裡要給 agent 看的欄位。福利（welfare）不給：那是公司自己寫的，
# 不能當員工評價，給了反而容易被誤用
PROFILE_FIELDS = {
    "industryDesc": "產業",
    "custLink": "官網",
    "profile": "公司介紹",
    "product": "主要商品／服務",
}


def company_profile(company_url: str | None) -> list[KnownFact]:
    """104 公司簡介當已知資料，讓 agent 一開始就知道品牌和產品。
    抓不到就不帶，調查照常進行。"""
    if not company_url:
        return []
    try:
        data = fetch_company(company_url)
        lines = [
            f"{label}：{data[key]}"
            for key, label in PROFILE_FIELDS.items()
            if data.get(key)
        ]
    except Exception:
        # 連不上、回應格式不對都算，不能讓整次調查跟著失敗
        log.exception("抓 104 公司簡介失敗：%s", company_url)
        return []
    if not lines:  # 公司不存在時 104 也回 200，只是欄位都是 null
        return []
    return [
        KnownFact(content="104 公司簡介\n" + "\n".join(lines), source_url=company_url)
    ]
