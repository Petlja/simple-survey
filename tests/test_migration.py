from datetime import datetime, timezone

import pytest
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, MetaData, String, Table, Text, create_engine, inspect


@pytest.fixture
def database_url(database_url):
    """A database created before responses had status, last_page and version."""
    metadata = MetaData()
    participants = Table(
        "participants",
        metadata,
        Column("token", String(64), primary_key=True),
        Column("label", String(255), nullable=False),
        Column("variables", JSON, nullable=False),
        Column("created_at", DateTime, nullable=False),
    )
    responses = Table(
        "responses",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("token", String(64), ForeignKey("participants.token"), nullable=False, unique=True),
        Column("response_data", Text, nullable=False),
        Column("submitted_at", DateTime, nullable=False),
    )
    engine = create_engine(database_url)
    metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            participants.insert(),
            [
                {"token": "answered", "label": "Answered", "variables": {"group": 1}, "created_at": now},
                {"token": "unanswered", "label": "Unanswered", "variables": {"group": 1}, "created_at": now},
            ],
        )
        connection.execute(responses.insert(), {"token": "answered", "response_data": '{"q1": "a"}', "submitted_at": now})
    engine.dispose()
    return database_url


def test_missing_columns_are_added(app, database_url):
    engine = create_engine(database_url)
    columns = {column["name"] for column in inspect(engine).get_columns("responses")}
    engine.dispose()
    assert {"status", "last_page", "version"} <= columns


def test_existing_response_counts_as_submitted(api):
    stored = api.stored("answered")
    assert stored["status"] == "submitted"
    assert stored["answers"] == {"q1": "a"}
    assert stored["last_page"] is None
    page = api.page("answered")
    assert page.completed
    assert page.value("version") is None
    assert not api.page("unanswered").completed


def test_existing_response_accepts_one_write_without_a_version(api):
    assert api.save("answered", {"q1": "b"}, None, "v1", page=1).status_code == 200
    assert api.stored("answered")["status"] == "submitted"
    assert api.save("answered", {"q1": "c"}, None, "v2").status_code == 409


def test_migrated_database_starts_again(app, make_app):
    assert make_app().test_client().get("/s/answered").status_code == 200
