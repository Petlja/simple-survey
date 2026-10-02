import pytest

MALFORMED_BODIES = {
    "not JSON": {"data": "x", "content_type": "text/plain"},
    "JSON array": {"json": [1]},
    "answers missing": {"json": {"expected_version": None, "new_version": "v1"}},
    "answers not an object": {"json": {"answers": [], "expected_version": None, "new_version": "v1"}},
    "expected_version not a string": {"json": {"answers": {}, "expected_version": 1, "new_version": "v1"}},
    "new_version missing": {"json": {"answers": {}, "expected_version": None}},
    "new_version empty": {"json": {"answers": {}, "expected_version": None, "new_version": ""}},
    "new_version over 64 characters": {"json": {"answers": {}, "expected_version": None, "new_version": "v" * 65}},
    "new_version not a string": {"json": {"answers": {}, "expected_version": None, "new_version": 5}},
}


@pytest.mark.parametrize("endpoint", ["save", "submit"])
@pytest.mark.parametrize("body", MALFORMED_BODIES.values(), ids=list(MALFORMED_BODIES))
def test_malformed_write_is_rejected(client, api, participant, endpoint, body):
    token = participant("t1")
    assert client.post(f"/api/{endpoint}/{token}", **body).status_code == 400
    assert api.stored(token) is None
    assert api.questions(token) == {}


@pytest.mark.parametrize("page", [-1, True, "1", 1.5])
def test_save_rejects_invalid_page(api, participant, page):
    token = participant("t1")
    assert api.save(token, {}, None, "v1", page=page).status_code == 400
    assert api.stored(token) is None


@pytest.mark.parametrize("endpoint", ["save", "submit"])
def test_write_for_unknown_token_is_not_found(client, endpoint):
    body = {"answers": {}, "expected_version": None, "new_version": "v1"}
    assert client.post(f"/api/{endpoint}/unknown", json=body).status_code == 404


def test_save_stores_an_incomplete_draft(api, participant):
    token = participant("t1")
    # Required q2 is missing; saves are not validated.
    assert api.save(token, {"q1": "a"}, None, "v1", page=0).status_code == 200
    stored = api.stored(token)
    assert stored["status"] == "draft"
    assert stored["answers"] == {"q1": "a"}
    assert stored["last_page"] == 0
    assert set(api.questions(token)) == {"q1"}


def test_each_save_names_the_previous_version(api, participant):
    token = participant("t1")
    longest = "w" * 64
    assert api.save(token, {"q1": "a"}, None, "v1", page=0).status_code == 200
    assert api.save(token, {"q1": "b"}, "v1", longest, page=1).status_code == 200
    assert api.save(token, {"q1": "c"}, longest, "v3").status_code == 200
    stored = api.stored(token)
    assert stored["answers"] == {"q1": "c"}
    assert stored["last_page"] is None


def test_submit_marks_the_response_submitted(api, participant):
    token = participant("t1")
    api.save(token, {"q1": "a"}, None, "v1", page=0)
    assert api.submit(token, {"q1": "a", "q2": "t"}, "v1", "v2").status_code == 200
    stored = api.stored(token)
    assert stored["status"] == "submitted"
    assert stored["answers"] == {"q1": "a", "q2": "t"}
    assert set(api.questions(token)) == {"q1", "q2"}


def test_submit_without_an_earlier_save(api, participant):
    token = participant("t1")
    assert api.submit(token, {"q1": "a"}, None, "v1").status_code == 200
    assert api.stored(token)["status"] == "submitted"
    assert set(api.questions(token)) == {"q1"}


def test_save_after_submit_keeps_the_response_submitted(api, participant):
    token = participant("t1")
    api.submit(token, {"q1": "a", "q2": "t"}, None, "v1")
    assert api.save(token, {"q1": "b"}, "v1", "v2", page=1).status_code == 200
    stored = api.stored(token)
    assert stored["status"] == "submitted"
    assert stored["answers"] == {"q1": "b"}
    assert stored["last_page"] == 1
    assert api.submit(token, {"q1": "c"}, "v2", "v3").status_code == 200
    assert api.stored(token)["answers"] == {"q1": "c"}


def test_writes_record_when_each_question_is_first_answered(api, participant):
    token = participant("t1")
    api.save(token, {"q1": "a"}, None, "v1", page=0)
    first = api.questions(token)
    assert set(first) == {"q1"}

    api.save(token, {"q1": "b", "q2": "t"}, "v1", "v2", page=0)
    api.submit(token, {"q2": "t", "q3": "x"}, "v2", "v3")
    answered = api.questions(token)
    assert set(answered) == {"q1", "q2", "q3"}
    assert answered["q1"] == first["q1"]
    assert answered["q1"] <= answered["q2"] <= answered["q3"]


def test_rejected_write_records_no_questions(api, participant):
    token = participant("t1")
    api.save(token, {"q1": "a"}, None, "v1")
    assert api.save(token, {"q2": "t"}, "stale", "v2").status_code == 409
    assert set(api.questions(token)) == {"q1"}


def test_participant_questions_api_lists_all_records(client, api, participant, admin_headers):
    t1, t2 = participant("t1", label="Ana"), participant("t2", label="Bo")
    api.save(t1, {"q1": "a"}, None, "v1")
    api.save(t2, {"q1": "b", "q2": "t"}, None, "w1")

    assert client.get("/api/participant-questions").status_code == 401
    rows = client.get("/api/participant-questions", headers=admin_headers).get_json()
    assert sorted((r["label"], r["question_name"]) for r in rows) == [
        ("Ana", "q1"), ("Bo", "q1"), ("Bo", "q2"),
    ]
    assert all(r["first_answered_at"] for r in rows)
