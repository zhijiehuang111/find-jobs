from judge import jd_to_text


def make_detail(**jd_overrides) -> dict:
    """最小的 104 detail，只放 jd_to_text 會讀的欄位。"""
    job_detail = {
        "jobCategory": [{"code": "2007001004", "description": "軟體工程師"}],
        "manageResp": "",
        "businessTrip": "",
        "workPeriodTags": [],
        "delegatedRecruit": "",
        "jobDescription": "開發後端 API",
    }
    job_detail.update(jd_overrides)
    return {
        "header": {"jobName": "後端工程師", "custName": "某某科技"},
        "industry": "電腦軟體服務業",
        "employees": "50人",
        "jobDetail": job_detail,
        "condition": {
            "workExp": "1年以上",
            "edu": "大學",
            "major": ["資訊工程相關"],
            "specialty": [{"code": "1", "description": "Python"}],
            "skill": [],
            "other": "",
        },
    }


def test_empty_fields_are_omitted():
    text = jd_to_text(make_detail())

    assert "職稱：後端工程師" in text
    assert "管理責任" not in text
    assert "工作技能" not in text
    assert text.endswith("【工作內容】\n開發後端 API")


def test_list_fields_flatten_both_shapes():
    # major 是純字串，specialty 是 {code, description}
    text = jd_to_text(make_detail())

    assert "科系要求：資訊工程相關" in text
    assert "擅長工具：Python" in text


def test_shift_tags_and_delegated_recruit():
    text = jd_to_text(make_detail(workPeriodTags=[1, 99], delegatedRecruit="某人力"))

    assert "排班說明：需輪班、99" in text
    assert "委託招募：由人力業者代為招募（某人力）" in text
