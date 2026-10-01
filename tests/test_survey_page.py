def test_unknown_token_is_not_found(client):
    assert client.get("/s/unknown").status_code == 404


def test_new_participant_gets_an_empty_survey(api, participant):
    page = api.page(participant("t1"))
    assert page.response.status_code == 200
    assert not page.completed
    assert page.value("previousAnswers") is None
    assert page.value("lastPage") is None
    assert page.value("version") is None


def test_survey_page_is_not_kept_in_the_browser_cache(api, participant):
    # The Back button would otherwise show answers and a version from an earlier visit.
    assert api.page(participant("t1")).response.headers["Cache-Control"] == "no-store"


def test_draft_reopens_with_answers_page_and_version(api, participant):
    token = participant("t1")
    api.save(token, {"q1": "a"}, None, "v1", page=1)
    page = api.page(token)
    assert not page.completed
    assert page.value("previousAnswers") == {"q1": "a"}
    assert page.value("lastPage") == 1
    assert page.value("version") == "v1"


def test_submitted_response_shows_the_completed_view(api, participant):
    token = participant("t1")
    api.submit(token, {"q1": "a"}, None, "v1")
    page = api.page(token)
    assert page.completed
    assert page.value("previousAnswers") == {"q1": "a"}
    assert page.value("version") == "v1"


def test_stored_answers_cannot_close_the_script(api, participant):
    token = participant("t1")
    hostile = "</script><script>alert(1)</script>"
    api.save(token, {"q2": hostile}, None, "v1", page=0)
    page = api.page(token)
    assert "</script><script>alert(1)" not in page.html
    assert page.value("previousAnswers") == {"q2": hostile}
