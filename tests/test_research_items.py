"""find-jobs 的公司調查項目：起始日由程式算好，不讓模型自己算。"""

from datetime import date

from research_items import research_items


def criteria(today: date) -> dict[str, str]:
    return {item.key: item.criteria for item in research_items(today)}


def test_since_dates_count_whole_years_back_from_today() -> None:
    # 以年為單位放寬：近期動向從去年 1/1 起，員工評價從三年前的 1/1 起
    got = criteria(date(2030, 6, 1))

    assert "2029-01-01" in got["recent_news"]
    assert "2027-01-01" in got["employee_reviews"]


def test_since_dates_move_with_the_year() -> None:
    # 不能是啟動時算好的常數：API 一跑好幾個月，跨年後要跟著變
    assert "2030-01-01" in criteria(date(2031, 1, 1))["recent_news"]
