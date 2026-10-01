"""Autosave and conflict handling of the survey page, driven in Chromium."""

import json
import re
import threading
import time
import urllib.request
import uuid

import pytest
from werkzeug.serving import make_server

from simple_survey.app import create_app
from simple_survey.models import Participant, Response, db

sync_api = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

CONFLICT_ALERT = "Odgovori su u međuvremenu izmenjeni u drugom prozoru. Stranica će biti ponovo učitana."
UNSAVED_MESSAGE = "Odgovori nisu snimljeni. Proverite internet vezu i pokušajte ponovo."
SAVE_URL = "**/api/save/**"


def is_save(response):
    return "/api/save/" in response.url


def is_submit(response):
    return "/api/submit/" in response.url


def wait_until(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


class Gate:
    """Route handler that holds requests until release()."""

    def __init__(self):
        self.held = []
        self.opened = False

    def __call__(self, route):
        if self.opened:
            route.continue_()
        else:
            self.held.append(route)

    def release(self):
        self.opened = True
        for route in self.held:
            route.continue_()


class SurveyTab:
    """A browser tab showing a participant's survey; alerts are accepted and recorded."""

    def __init__(self, context, url):
        self.page = context.new_page()
        self.alerts = []
        self.writes = []
        self.errors = []
        self.page.on("dialog", self._accept_dialog)
        self.page.on("response", self._record_write)
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(url)
        self.wait_ready()

    def _accept_dialog(self, dialog):
        self.alerts.append(dialog.message)
        dialog.accept()

    def _record_write(self, response):
        if is_save(response) or is_submit(response):
            kind = "save" if is_save(response) else "submit"
            self.writes.append((kind, response.status, response.request.post_data_json))

    def wait_ready(self):
        self.page.locator(".sd-question, #updateBtn").first.wait_for()

    def reload(self):
        self.page.reload()
        self.wait_ready()

    def choose(self, question, value):
        self.page.locator(f'[data-name="{question}"] label:has(input[value="{value}"])').click()

    def field(self, question):
        return self.page.locator(f'[data-name="{question}"] input, [data-name="{question}"] textarea').first

    def type_text(self, question, text):
        self.field(question).fill(text)
        self.field(question).press("Tab")

    def next(self):
        self.page.locator(".sd-navigation__next-btn").click()

    def complete(self):
        self.page.locator(".sd-navigation__complete-btn").click()

    def wait_page(self, name):
        self.page.wait_for_function("name => survey.currentPage && survey.currentPage.name === name", arg=name)

    def wait_saved(self):
        """Wait until the page's queued writes have finished."""
        self.page.evaluate("() => Promise.all([writeQueue, lastSave]).then(() => true)")

    def data(self):
        return self.page.evaluate("survey.data")

    def page_name(self):
        return self.page.evaluate("survey.currentPage.name")

    def fill_to_last_page(self):
        self.choose("q1", "a")
        self.type_text("q2", "t")
        self.next()
        self.wait_page("p2")
        self.choose("q3", "y")
        self.next()
        self.wait_page("p3")


@pytest.fixture(scope="module")
def server(survey_path, tmp_path_factory):
    try:
        urllib.request.urlopen("https://unpkg.com/survey-core@3.1.2/package.json", timeout=10).close()
    except OSError as error:
        pytest.skip(f"SurveyJS cannot be loaded from unpkg.com: {error}")
    database = tmp_path_factory.mktemp("browser") / "survey.db"
    app = create_app(
        survey_json_path=survey_path,
        database_url=f"sqlite:///{database}",
        admin_token="unused",
        participants_seed=[],
    )
    http = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    yield app, f"http://127.0.0.1:{http.server_port}"
    http.shutdown()
    http.server_close()
    with app.app_context():
        db.engine.dispose()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except sync_api.Error as error:
            pytest.skip(f"Chromium is not installed (uv run playwright install chromium): {str(error).splitlines()[0]}")
        yield browser
        browser.close()


@pytest.fixture
def new_context(browser):
    contexts = []

    def make():
        contexts.append(browser.new_context())
        return contexts[-1]

    yield make
    for context in contexts:
        context.close()


@pytest.fixture
def open_tab(server, new_context):
    """Open a participant's survey; without a context each tab acts as a separate browser."""
    _, base_url = server
    tabs = []

    def open_tab(token, context=None):
        tabs.append(SurveyTab(context or new_context(), f"{base_url}/s/{token}"))
        return tabs[-1]

    yield open_tab
    assert [error for tab in tabs for error in tab.errors] == []


@pytest.fixture
def participant(server, request):
    """Add a group-1 participant labelled with the test name and return its token."""
    app, _ = server

    def add():
        token = uuid.uuid4().hex
        with app.app_context():
            db.session.add(Participant(token=token, label=request.node.name, variables={"group": 1}))
            db.session.commit()
        return token

    return add


@pytest.fixture
def stored(server):
    app, _ = server

    def read(token):
        with app.app_context():
            response = db.session.query(Response).filter_by(token=token).one_or_none()
            if response is None:
                return None
            return {
                "status": response.status,
                "answers": json.loads(response.response_data),
                "last_page": response.last_page,
            }

    return read


def test_answer_is_saved_at_once_as_draft(open_tab, participant, stored):
    token = participant()
    tab = open_tab(token)
    with tab.page.expect_response(is_save) as saved:
        tab.choose("q1", "b")
    body = saved.value.request.post_data_json
    assert saved.value.status == 200
    assert body["expected_version"] is None
    assert re.fullmatch("[0-9a-f]{32}", body["new_version"])
    # Required q2 is still empty.
    assert stored(token) == {"status": "draft", "answers": {"q1": "b"}, "last_page": 0}


def test_reload_returns_to_the_last_page(open_tab, participant, stored):
    token = participant()
    tab = open_tab(token)
    tab.choose("q1", "b")
    tab.type_text("q2", "hello")
    tab.next()
    tab.wait_page("p2")
    tab.wait_saved()
    tab.reload()
    assert tab.page_name() == "p2"
    assert tab.data() == {"q1": "b", "q2": "hello"}
    assert stored(token)["last_page"] == 1


def test_page_change_waits_for_a_pending_save(open_tab, participant, stored):
    token = participant()
    tab = open_tab(token)
    tab.choose("q1", "a")
    tab.type_text("q2", "x")
    tab.wait_saved()
    gate = Gate()
    tab.page.route(SAVE_URL, gate)
    tab.choose("q1", "c")
    tab.next()
    tab.page.wait_for_timeout(500)
    assert tab.page_name() == "p1"
    gate.release()
    tab.wait_page("p2")
    tab.wait_saved()
    assert stored(token)["answers"]["q1"] == "c"
    assert {status for _, status, _ in tab.writes} == {200}


def test_quick_changes_are_saved_one_at_a_time(open_tab, participant, stored):
    token = participant()
    tab = open_tab(token)
    gate = Gate()
    tab.page.route(SAVE_URL, gate)
    for value in ["a", "b", "c"]:
        tab.choose("q1", value)
    tab.page.wait_for_timeout(300)
    assert len(gate.held) == 1
    gate.release()
    tab.wait_saved()
    assert [status for _, status, _ in tab.writes] == [200, 200, 200]
    bodies = [body for _, _, body in tab.writes]
    assert [body["expected_version"] for body in bodies[1:]] == [body["new_version"] for body in bodies[:-1]]
    assert stored(token)["answers"] == {"q1": "c"}


def test_stale_browser_alerts_and_reloads(open_tab, participant, stored, caplog):
    token = participant()
    first, second = open_tab(token), open_tab(token)
    with first.page.expect_response(is_save):
        first.choose("q1", "a")
    with second.page.expect_navigation():
        with second.page.expect_response(is_save) as rejected:
            second.choose("q1", "c")
    second.wait_ready()
    assert rejected.value.status == 409
    assert second.alerts == [CONFLICT_ALERT]
    assert second.data() == {"q1": "a"}
    assert stored(token)["answers"] == {"q1": "a"}
    assert "Write conflict on /api/save for participant 'test_stale_browser_alerts_and_reloads'" in caplog.text


def test_stale_browser_does_not_change_page(open_tab, participant, stored):
    token = participant()
    first = open_tab(token)
    first.choose("q1", "a")
    first.type_text("q2", "x")
    first.wait_saved()
    second = open_tab(token)
    first.choose("q1", "b")
    first.wait_saved()
    gate = Gate()
    second.page.route(SAVE_URL, gate)
    second.choose("q1", "c")
    second.next()
    with second.page.expect_navigation():
        gate.release()
    second.wait_ready()
    assert second.alerts == [CONFLICT_ALERT]
    assert second.page_name() == "p1"
    assert [status for _, status, _ in second.writes] == [409]
    assert stored(token)["answers"] == {"q1": "b", "q2": "x"}


def test_submit_and_later_edit_keep_the_response_submitted(open_tab, participant, stored):
    token = participant()
    tab = open_tab(token)
    tab.fill_to_last_page()
    with tab.page.expect_response(is_submit) as submitted:
        tab.complete()
    assert submitted.value.status == 200
    assert stored(token)["status"] == "submitted"
    tab.reload()
    tab.page.locator("#updateBtn").click()
    tab.page.locator(".sd-question").first.wait_for()
    with tab.page.expect_response(is_save) as saved:
        tab.choose("q1", "c")
    assert saved.value.status == 200
    assert stored(token)["status"] == "submitted"
    assert stored(token)["answers"]["q1"] == "c"


def test_complete_waits_for_a_pending_save(open_tab, participant, stored):
    token = participant()
    tab = open_tab(token)
    tab.fill_to_last_page()
    tab.wait_saved()
    gate = Gate()
    tab.page.route(SAVE_URL, gate)
    tab.field("q4").fill("last words")
    tab.complete()
    tab.page.wait_for_timeout(300)
    assert len(gate.held) == 1
    assert not [kind for kind, _, _ in tab.writes if kind == "submit"]
    with tab.page.expect_response(is_submit) as submitted:
        gate.release()
    assert submitted.value.status == 200
    assert stored(token)["status"] == "submitted"
    assert stored(token)["answers"]["q4"] == "last words"


def test_unsaved_change_blocks_page_change_until_online(open_tab, participant, new_context, stored):
    token = participant()
    context = new_context()
    tab = open_tab(token, context)
    tab.choose("q1", "a")
    tab.type_text("q2", "x")
    tab.wait_saved()
    context.set_offline(True)
    tab.choose("q1", "b")
    tab.wait_saved()
    tab.next()
    sync_api.expect(tab.page.get_by_text(UNSAVED_MESSAGE).first).to_be_visible()
    assert tab.page_name() == "p1"
    context.set_offline(False)
    tab.next()
    tab.wait_page("p2")
    tab.wait_saved()
    assert tab.alerts == []
    assert stored(token)["answers"] == {"q1": "b", "q2": "x"}


def test_text_typed_before_closing_the_tab_is_saved(open_tab, participant, stored):
    token = participant()
    tab = open_tab(token)
    tab.choose("q1", "a")
    tab.wait_saved()
    tab.field("q2").fill("typed")
    tab.page.close(run_before_unload=True)
    assert wait_until(lambda: stored(token)["answers"].get("q2") == "typed")


def test_reload_right_after_typing_shows_the_text(open_tab, participant):
    token = participant()
    tab = open_tab(token)
    tab.choose("q1", "a")
    tab.wait_saved()
    tab.field("q2").fill("typed")
    tab.reload()
    # The save sent while leaving usually reaches the server after the page was rendered again.
    assert tab.data() == {"q1": "a", "q2": "typed"}
    with tab.page.expect_response(is_save) as saved:
        tab.choose("q1", "b")
    assert saved.value.status == 200
    assert tab.alerts == []


def test_back_button_shows_the_current_answers(open_tab, participant, server):
    _, base_url = server
    token = participant()
    tab = open_tab(token)
    tab.choose("q1", "a")
    tab.wait_saved()
    tab.page.goto(f"{base_url}/")
    tab.page.go_back()
    tab.wait_ready()
    assert tab.data() == {"q1": "a"}
    with tab.page.expect_response(is_save) as saved:
        tab.choose("q1", "b")
    assert saved.value.status == 200


def test_survey_works_when_session_storage_is_blocked(open_tab, participant, new_context, stored):
    token = participant()
    context = new_context()
    context.add_init_script(
        "Object.defineProperty(window, 'sessionStorage', { get() { throw new DOMException('blocked', 'SecurityError'); } });"
    )
    tab = open_tab(token, context)
    tab.choose("q1", "a")
    tab.wait_saved()
    tab.field("q2").fill("typed")
    tab.reload()
    assert tab.page_name() == "p1"
    assert wait_until(lambda: stored(token)["answers"] == {"q1": "a", "q2": "typed"})
