def test_responses_require_the_admin_token(client):
    assert client.get("/api/responses").status_code == 401
    assert client.get("/api/responses", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_responses_fail_without_a_configured_admin_token(make_app):
    client = make_app(admin_token="").test_client()
    assert client.get("/api/responses", headers={"Authorization": "Bearer "}).status_code == 500


def test_responses_include_drafts(client, api, participant, admin_headers):
    api.save(participant("draft", label="Draft"), {"q1": "a"}, None, "v1", page=1)
    api.submit(participant("done", label="Done"), {"q1": "b"}, None, "v2")
    rows = {row["token"]: row for row in client.get("/api/responses", headers=admin_headers).get_json()}
    saved_at = [row.pop("submitted_at") for row in rows.values()]
    assert all(isinstance(value, str) for value in saved_at)
    assert rows == {
        "draft": {"token": "draft", "label": "Draft", "status": "draft", "last_page": 1, "answers": {"q1": "a"}},
        "done": {"token": "done", "label": "Done", "status": "submitted", "last_page": None, "answers": {"q1": "b"}},
    }


def test_deleting_a_participant_deletes_the_response(client, api, participant, admin_headers):
    token = participant("t1")
    api.save(token, {"q1": "a"}, None, "v1", page=0)
    assert client.delete(f"/api/participants/{token}", headers=admin_headers).status_code == 204
    assert api.stored(token) is None
