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


def test_submit_without_an_earlier_save(api, participant):
    token = participant("t1")
    assert api.submit(token, {"q1": "a"}, None, "v1").status_code == 200
    assert api.stored(token)["status"] == "submitted"


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
