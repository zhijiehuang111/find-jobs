from datetime import UTC, datetime

import pytest


def slugs(client, **params) -> list[str]:
    response = client.get("/api/jobs", params=params)
    assert response.status_code == 200
    return [job["slug"] for job in response.json()]


def label(client, slug, human_label, human_note=None) -> dict:
    response = client.post(
        f"/api/jobs/{slug}/label",
        json={"human_label": human_label, "human_note": human_note},
    )
    assert response.status_code == 200
    return response.json()


def test_job_is_flattened_for_frontend(client, add_job):
    add_job("abc")

    job = client.get("/api/jobs").json()[0]

    assert job["url"] == "https://www.104.com.tw/job/abc"
    assert job["job_name"] == "後端工程師"
    assert job["cust_name"] == "某某科技"
    assert job["address"] == "台北市信義區"
    assert job["salary_low"] == 60000
    assert job["salary_high"] == 80000
    assert job["salary"] == "月薪60,000~80,000元"


def test_rejected_job_without_detail_still_lists(client, add_job):
    add_job("rejected", rejected=True)

    job = client.get("/api/jobs").json()[0]

    assert job["salary"] is None
    assert job["fit"] is None
    assert job["rejected_by"] == "salary_monthly"


def test_verdict_filters(client, add_job):
    add_job("fit", fit=True)
    add_job("unfit", fit=False)
    add_job("filtered", rejected=True)

    assert slugs(client, verdict="fit") == ["fit"]
    assert slugs(client, verdict="unfit") == ["unfit"]
    assert slugs(client, verdict="filtered") == ["filtered"]
    assert set(slugs(client)) == {"fit", "unfit", "filtered"}


def test_inbox_is_fit_and_unlabeled(client, add_job):
    add_job("inbox")
    add_job("labeled", human_label="unsure")
    add_job("unfit", fit=False)

    assert slugs(client, verdict="fit", labeled="false") == ["inbox"]


def test_starred_filter(client, add_job):
    add_job("starred", starred=True)
    add_job("plain")

    assert slugs(client, starred="true") == ["starred"]
    assert slugs(client, starred="false") == ["plain"]


def test_default_sort_is_newest_first_seen(client, add_job):
    add_job("old", age_days=2)
    add_job("new", age_days=0)
    add_job("middle", age_days=1)

    assert slugs(client) == ["new", "middle", "old"]


def test_starred_sort_is_newest_star_with_unstarred_last(client, add_job):
    add_job("first", starred=True, starred_at=datetime(2026, 1, 1, tzinfo=UTC))
    add_job("second", starred=True, starred_at=datetime(2026, 2, 1, tzinfo=UTC))
    add_job("plain")

    assert slugs(client, sort="starred") == ["second", "first", "plain"]


def test_limit_and_offset(client, add_job):
    add_job("a", age_days=0)
    add_job("b", age_days=1)
    add_job("c", age_days=2)

    assert slugs(client, limit=1, offset=1) == ["b"]


@pytest.mark.parametrize(
    "params",
    [
        {"verdict": "nope"},
        {"sort": "nope"},
        {"limit": 0},
        {"limit": 501},
        {"offset": -1},
    ],
)
def test_invalid_list_params_are_rejected(client, params):
    assert client.get("/api/jobs", params=params).status_code == 422


def test_stats_counts_each_tab(client, add_job):
    add_job("inbox")
    add_job("fit-labeled", human_label="no", starred=False)
    add_job("unfit-open", fit=False)
    add_job("unfit-labeled", fit=False, human_label="yes", starred=True)
    add_job("filtered-open", rejected=True)

    assert client.get("/api/stats").json() == {
        "fit": 2,
        "unfit": 2,
        "filtered": 1,
        "inbox": 1,
        "unfit_open": 1,
        "filtered_open": 1,
        "starred": 1,
    }


def test_label_yes_stars_the_job(client, add_job):
    add_job("abc")

    job = label(client, "abc", "yes")

    assert job["human_label"] == "yes"
    assert job["starred"] is True
    assert job["starred_at"] is not None


def test_label_yes_keeps_original_star_time(client, add_job):
    starred_at = datetime(2026, 1, 1, tzinfo=UTC)
    add_job("abc", starred=True, starred_at=starred_at)

    job = label(client, "abc", "yes")

    assert datetime.fromisoformat(job["starred_at"]) == starred_at


@pytest.mark.parametrize("new_label", ["no", None])
def test_taking_back_yes_removes_the_star(client, add_job, new_label):
    add_job("abc")
    label(client, "abc", "yes")

    job = label(client, "abc", new_label)

    assert job["human_label"] == new_label
    assert job["starred"] is False
    assert job["starred_at"] is None


def test_yes_to_unsure_keeps_the_star(client, add_job):
    add_job("abc")
    label(client, "abc", "yes")

    job = label(client, "abc", "unsure")

    assert job["starred"] is True


def test_label_no_leaves_manual_star_alone(client, add_job):
    add_job("abc", starred=True, starred_at=datetime(2026, 1, 1, tzinfo=UTC))

    job = label(client, "abc", "no")

    assert job["starred"] is True


@pytest.mark.parametrize(
    ("fit", "new_label", "note_kept"),
    [
        (True, "yes", False),  # 同意 LLM，不用寫理由
        (False, "no", False),
        (True, "no", True),  # 跟 LLM 不同，理由留著
        (False, "yes", True),
        (True, "unsure", True),
    ],
)
def test_note_is_only_kept_when_it_explains_something(
    client, add_job, fit, new_label, note_kept
):
    add_job("abc", fit=fit)

    job = label(client, "abc", new_label, "我的理由")

    assert job["human_note"] == ("我的理由" if note_kept else None)


def test_label_no_clears_note_on_rejected_job(client, add_job):
    add_job("abc", rejected=True)

    job = label(client, "abc", "no", "我的理由")

    assert job["human_note"] is None


def test_clearing_label_clears_note(client, add_job):
    add_job("abc")
    label(client, "abc", "unsure", "我的理由")

    job = label(client, "abc", None, "我的理由")

    assert job["human_label"] is None
    assert job["human_note"] is None


def test_label_outside_vocabulary_is_rejected(client, add_job):
    add_job("abc")

    response = client.post("/api/jobs/abc/label", json={"human_label": "maybe"})

    assert response.status_code == 422


def test_label_is_persisted(client, add_job):
    add_job("abc")
    label(client, "abc", "unsure")

    assert client.get("/api/jobs").json()[0]["human_label"] == "unsure"


def test_star_sets_and_clears_time(client, add_job):
    add_job("abc")

    starred = client.post("/api/jobs/abc/star", json={"starred": True}).json()
    unstarred = client.post("/api/jobs/abc/star", json={"starred": False}).json()

    assert starred["starred"] is True
    assert starred["starred_at"] is not None
    assert unstarred["starred"] is False
    assert unstarred["starred_at"] is None


def test_star_again_keeps_original_time(client, add_job):
    starred_at = datetime(2026, 1, 1, tzinfo=UTC)
    add_job("abc", starred=True, starred_at=starred_at)

    job = client.post("/api/jobs/abc/star", json={"starred": True}).json()

    assert datetime.fromisoformat(job["starred_at"]) == starred_at


@pytest.mark.parametrize(
    ("path", "body"),
    [("label", {"human_label": "yes"}), ("star", {"starred": True})],
)
def test_unknown_slug_is_404(client, db, path, body):
    response = client.post(f"/api/jobs/nope/{path}", json=body)

    assert response.status_code == 404
    assert "nope" in response.json()["detail"]
