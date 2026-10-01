import json
import os
import re

import pytest
from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import make_url

from simple_survey.app import create_app
from simple_survey.models import Participant, db

ADMIN_TOKEN = "test-admin-token"

# Test participants are in group 1: they see p1-p3, so p2 is visible page 1.
SURVEY = {
    "title": "Test survey",
    "pages": [
        {"name": "p0", "visibleIf": "{group} = 2", "elements": [
            {"type": "radiogroup", "name": "q0", "isRequired": True, "choices": ["m", "n"]},
        ]},
        {"name": "p1", "visibleIf": "{group} = 1", "elements": [
            {"type": "radiogroup", "name": "q1", "isRequired": True, "choices": ["a", "b", "c"]},
            {"type": "text", "name": "q2", "isRequired": True},
        ]},
        {"name": "p2", "visibleIf": "{group} = 1", "elements": [
            {"type": "radiogroup", "name": "q3", "isRequired": True, "choices": ["x", "y", "z"]},
        ]},
        {"name": "p3", "visibleIf": "{group} = 1", "elements": [
            {"type": "comment", "name": "q4"},
        ]},
    ],
}


class RenderedPage:
    def __init__(self, response):
        self.response = response
        self.html = response.get_data(as_text=True)

    @property
    def completed(self):
        return "Upitnik je već popunjen" in self.html

    def value(self, name):
        """Return the JSON value the server rendered into script variable `name`."""
        match = re.search(rf"(?:const|let) {name} = (?:\w+ \? [\w.]+ : )?(.*);", self.html)
        assert match, f"{name} is not rendered"
        return json.loads(match.group(1))


class SurveyApi:
    """Writes answers like the survey page does and reads them back like an admin."""

    def __init__(self, client):
        self.client = client

    def save(self, token, answers, expected, new, page=None):
        body = {"answers": answers, "expected_version": expected, "new_version": new}
        if page is not None:
            body["page"] = page
        return self.client.post(f"/api/save/{token}", json=body)

    def submit(self, token, answers, expected, new):
        body = {"answers": answers, "expected_version": expected, "new_version": new}
        return self.client.post(f"/api/submit/{token}", json=body)

    def stored(self, token):
        rows = self.client.get("/api/responses", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}).get_json()
        return next((row for row in rows if row["token"] == token), None)

    def page(self, token):
        return RenderedPage(self.client.get(f"/s/{token}"))


@pytest.fixture(scope="session")
def survey_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("survey") / "survey.json"
    path.write_text(json.dumps(SURVEY), encoding="utf-8")
    return str(path)


@pytest.fixture
def database_url(tmp_path):
    """Temporary SQLite unless SIMPLE_SURVEY_TEST_DATABASE_URL names a database, which is wiped."""
    url = os.environ.get("SIMPLE_SURVEY_TEST_DATABASE_URL")
    if not url:
        return f"sqlite:///{tmp_path / 'survey.db'}"
    if "test" not in (make_url(url).database or ""):
        pytest.exit("SIMPLE_SURVEY_TEST_DATABASE_URL must name a throwaway database with 'test' in its name")
    engine = create_engine(url)
    metadata = MetaData()
    metadata.reflect(engine)
    metadata.drop_all(engine)
    engine.dispose()
    return url


@pytest.fixture
def make_app(survey_path, database_url):
    apps = []

    def make(admin_token=ADMIN_TOKEN):
        # An empty seed keeps a local participants.json out of the test database.
        app = create_app(
            survey_json_path=survey_path,
            database_url=database_url,
            admin_token=admin_token,
            participants_seed=[],
        )
        apps.append(app)
        return app

    yield make
    for app in apps:
        with app.app_context():
            db.engine.dispose()


@pytest.fixture
def app(make_app):
    return make_app()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@pytest.fixture
def api(client):
    return SurveyApi(client)


@pytest.fixture
def participant(app):
    """Add a group-1 participant and return its token."""

    def add(token, label=None):
        with app.app_context():
            db.session.add(Participant(token=token, label=label or token, variables={"group": 1}))
            db.session.commit()
        return token

    return add
