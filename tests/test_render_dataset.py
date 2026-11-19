"""考卷轉 Markdown：每題一段，JD 是模型看到的那份文字，一個字都不能少。"""

from judge import jd_to_text
from render_dataset import render
from tests.test_judge import make_detail


def record(slug: str, label: str, reason: str, **jd_overrides) -> dict:
    return {
        "slug": slug,
        "url": f"https://www.104.com.tw/job/{slug}",
        "label": label,
        "reason": reason,
        "fetched_at": "2030-01-02T10:00:00+08:00",
        "detail": make_detail(**jd_overrides),
    }


def test_each_job_gets_its_own_section_with_label_and_reason():
    text = render(
        [record("aaa11", "yes", "技術對、規模剛好"), record("bbb22", "no", "要輪班")]
    )

    assert "# 考卷（2 題：yes 1、no 1）" in text
    first, second = text.split("\n## ")[1:]
    assert first.startswith("1. 後端工程師｜某某科技")
    assert "slug：`aaa11`" in first
    assert "label：yes" in first
    assert "reason：技術對、規模剛好" in first
    assert "https://www.104.com.tw/job/aaa11" in first
    assert second.startswith("2. 後端工程師｜某某科技")
    assert "label：no" in second


def test_jd_is_exactly_what_the_model_sees():
    jd = "第一行\n```\nJD 裡本來就有的 code block\n```\n最後一行"
    item = record("aaa11", "yes", "技術對", jobDescription=jd)

    text = render([item])

    assert jd_to_text(item["detail"]) in text
    # 包住 JD 的 fence 要比 JD 裡的 ``` 長，區塊才不會被提早關掉
    assert "````text\n" in text
