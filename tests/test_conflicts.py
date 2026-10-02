import json
import logging
import threading
import urllib.error
import urllib.request

import pytest
from werkzeug.serving import make_server

CONFLICT = {"code": 409, "message": "Answers were changed in another window", "status": "Conflict"}


def test_stale_save_is_rejected_and_changes_nothing(api, participant):
    token = participant("t1")
    api.save(token, {"q1": "a"}, None, "v1", page=0)
    api.save(token, {"q1": "b"}, "v1", "v2", page=1)
    response = api.save(token, {"q1": "stale", "q2": "t"}, "v1", "v3", page=2)
    assert response.status_code == 409
    assert response.get_json() == CONFLICT
    stored = api.stored(token)
    assert stored["answers"] == {"q1": "b"}
    assert stored["last_page"] == 1
    assert api.page(token).value("version") == "v2"
    assert set(api.questions(token)) == {"q1"}


@pytest.mark.parametrize("expected", [None, "unknown"])
def test_save_must_name_the_stored_version(api, participant, expected):
    token = participant("t1")
    api.save(token, {"q1": "a"}, None, "v1", page=0)
    assert api.save(token, {"q1": "b", "q2": "t"}, expected, "v2").status_code == 409
    assert api.stored(token)["answers"] == {"q1": "a"}
    assert set(api.questions(token)) == {"q1"}


def test_stale_submit_is_rejected_and_changes_nothing(api, participant):
    token = participant("t1")
    api.save(token, {"q1": "a"}, None, "v1", page=0)
    api.save(token, {"q1": "b"}, "v1", "v2", page=0)
    assert api.submit(token, {"q1": "stale", "q2": "t"}, "v1", "v3").status_code == 409
    stored = api.stored(token)
    assert stored["status"] == "draft"
    assert stored["answers"] == {"q1": "b"}
    assert set(api.questions(token)) == {"q1"}


def test_write_naming_a_version_creates_no_response(api, participant):
    token = participant("t1")
    assert api.submit(token, {"q1": "a"}, "v0", "v1").status_code == 409
    assert api.stored(token) is None
    assert api.questions(token) == {}


def test_conflicts_are_logged_without_the_token(api, participant, caplog):
    token = participant("secret-token", label="Ana")
    api.save(token, {"q1": "a"}, None, "v1", page=0)
    with caplog.at_level(logging.WARNING):
        api.save(token, {"q1": "b"}, "v0", "v2")
        api.submit(token, {"q1": "c"}, "v0", "v3")
    conflicts = [message for message in caplog.messages if message.startswith("Write conflict")]
    assert conflicts == [
        "Write conflict on /api/save for participant 'Ana': expected version 'v0', stored 'v1', rejected 'v2'",
        "Write conflict on /api/submit for participant 'Ana': expected version 'v0', stored 'v1', rejected 'v3'",
    ]
    assert "secret-token" not in caplog.text


def post_at_once(requests):
    """POST each (url, body) from its own thread, all released together; return the HTTP statuses."""
    barrier = threading.Barrier(len(requests))
    statuses = [None] * len(requests)

    def post(index):
        url, body = requests[index]
        request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        barrier.wait()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                statuses[index] = response.status
        except urllib.error.HTTPError as error:
            statuses[index] = error.code

    threads = [threading.Thread(target=post, args=(index,)) for index in range(len(requests))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return statuses


def test_only_one_of_simultaneous_writes_is_accepted(app, api, participant):
    token = participant("t1")
    server = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_port}/api"
    try:
        expected = None
        winner_questions = set()
        for round_no in range(3):
            # Saves race submits; in the first round they also race to create the response.
            requests = [
                (
                    f"{base_url}/{'submit' if index % 2 else 'save'}/{token}",
                    {"answers": {f"writer{index}": round_no}, "expected_version": expected, "new_version": f"r{round_no}w{index}"},
                )
                for index in range(10)
            ]
            statuses = post_at_once(requests)
            winners = [index for index, status in enumerate(statuses) if status == 200]
            assert len(winners) == 1 and statuses.count(409) == 9, statuses
            expected = f"r{round_no}w{winners[0]}"
            page = api.page(token)
            assert page.value("version") == expected
            assert page.value("previousAnswers") == {f"writer{winners[0]}": round_no}
            winner_questions.add(f"writer{winners[0]}")
            assert set(api.questions(token)) == winner_questions
    finally:
        server.shutdown()
        server.server_close()
