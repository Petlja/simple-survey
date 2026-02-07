import os
import json
import uuid
import sqlite3
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, jsonify, abort as flask_abort
from flask.views import MethodView
from flask_smorest import Api, Blueprint, abort
from marshmallow import Schema, fields

app = Flask(__name__)
DATABASE = os.path.join(os.path.dirname(__file__), "survey.db")
SURVEY_JSON_PATH = os.path.join(os.path.dirname(__file__), "survey.json")
PARTICIPANTS_SEED_PATH = os.path.join(os.path.dirname(__file__), "participants.json")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

# ---------------------------------------------------------------------------
# Flask-Smorest – auto-generates the OpenAPI spec from the schemas/decorators
# ---------------------------------------------------------------------------
app.config["API_TITLE"] = "Simple Survey API"
app.config["API_VERSION"] = "1.0.0"
app.config["OPENAPI_VERSION"] = "3.0.3"
app.config["OPENAPI_URL_PREFIX"] = "/docs"
app.config["OPENAPI_SWAGGER_UI_PATH"] = "/"
app.config["OPENAPI_SWAGGER_UI_URL"] = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
app.config["API_SPEC_OPTIONS"] = {
    "components": {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
            }
        }
    },
}

api = Api(app)


# ---------------------------------------------------------------------------
# Marshmallow schemas – drive OpenAPI request/response generation
# ---------------------------------------------------------------------------
class ParticipantSchema(Schema):
    token = fields.String(metadata={"format": "uuid"})
    label = fields.String(required=True)
    created_at = fields.String(metadata={"format": "date-time"})


class ParticipantCreateSchema(Schema):
    label = fields.String(required=True)


class SurveyResponseSchema(Schema):
    token = fields.String()
    label = fields.String()
    submitted_at = fields.String(metadata={"format": "date-time"})
    answers = fields.Dict()


class ErrorSchema(Schema):
    error = fields.String()


class StatusSchema(Schema):
    status = fields.String()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_survey_json():
    """Load the survey definition from the JSON file."""
    with open(SURVEY_JSON_PATH, "r") as f:
        return json.load(f)


def get_db():
    """Get a database connection."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def find_participant(token):
    """Find a participant by token in the database."""
    conn = get_db()
    row = conn.execute(
        "SELECT token, label FROM participants WHERE token = ?", (token,)
    ).fetchone()
    conn.close()
    if row:
        return {"token": row["token"], "label": row["label"]}
    return None


def require_admin(f):
    """Decorator that enforces Bearer token auth for admin endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not ADMIN_TOKEN:
            return jsonify({"error": "Admin token not configured"}), 500
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {ADMIN_TOKEN}":
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def init_db():
    """Initialize the database schema and seed participants on first run."""
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS participants (
            token TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL,
            response_data TEXT NOT NULL,
            submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (token) REFERENCES participants(token)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_responses_token ON responses(token);
    """
    )
    # Seed from participants.json if the table is empty and the file exists
    count = conn.execute("SELECT COUNT(*) FROM participants").fetchone()[0]
    if count == 0 and os.path.exists(PARTICIPANTS_SEED_PATH):
        with open(PARTICIPANTS_SEED_PATH, "r") as f:
            seed = json.load(f)["participants"]
        for p in seed:
            conn.execute(
                "INSERT OR IGNORE INTO participants (token, label) VALUES (?, ?)",
                (p["token"], p["label"]),
            )
    conn.commit()
    conn.close()


def is_completed(token):
    """Check if a participant has already submitted a response."""
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM responses WHERE token = ?", (token,)
    ).fetchone()
    conn.close()
    return row is not None


# ---------------------------------------------------------------------------
# Non-API routes
# ---------------------------------------------------------------------------
@app.route("/")
def home():
    """Simple landing page."""
    return "<h1>Simple Survey</h1>"


@app.route("/s/<token>")
def survey_page(token):
    """Serve the survey page for a given participant token."""
    participant = find_participant(token)
    if not participant:
        flask_abort(404)

    return render_template(
        "survey.html",
        token=token,
        survey_json=json.dumps(load_survey_json()),
        already_completed=is_completed(token),
    )


@app.route("/thank-you")
def thank_you():
    """Show a thank-you page after survey completion."""
    return render_template("thank_you.html")


# ---------------------------------------------------------------------------
# API Blueprints
# ---------------------------------------------------------------------------
participants_blp = Blueprint(
    "Participants", __name__,
    url_prefix="/api/participants",
    description="Manage survey participants",
)

survey_blp = Blueprint(
    "Survey", __name__,
    url_prefix="/api",
    description="Survey submission",
)

responses_blp = Blueprint(
    "Responses", __name__,
    url_prefix="/api",
    description="Survey responses",
)


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------
@participants_blp.route("/")
class ParticipantList(MethodView):

    @participants_blp.doc(security=[{"BearerAuth": []}])
    @participants_blp.response(200, ParticipantSchema(many=True))
    @require_admin
    def get(self):
        """List all participants."""
        conn = get_db()
        rows = conn.execute(
            "SELECT token, label, created_at FROM participants ORDER BY created_at"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @participants_blp.doc(security=[{"BearerAuth": []}])
    @participants_blp.arguments(ParticipantCreateSchema)
    @participants_blp.response(201, ParticipantSchema)
    @require_admin
    def post(self, body):
        """Create a new participant."""
        token = str(uuid.uuid4())
        conn = get_db()
        conn.execute(
            "INSERT INTO participants (token, label) VALUES (?, ?)",
            (token, body["label"]),
        )
        conn.commit()
        row = conn.execute(
            "SELECT token, label, created_at FROM participants WHERE token = ?",
            (token,),
        ).fetchone()
        conn.close()
        return dict(row)


@participants_blp.route("/<token>")
class ParticipantItem(MethodView):

    @participants_blp.doc(security=[{"BearerAuth": []}])
    @participants_blp.response(200, ParticipantSchema)
    @require_admin
    def get(self, token):
        """Get a single participant by token."""
        conn = get_db()
        row = conn.execute(
            "SELECT token, label, created_at FROM participants WHERE token = ?",
            (token,),
        ).fetchone()
        conn.close()
        if not row:
            abort(404, message="Participant not found")
        return dict(row)

    @participants_blp.doc(security=[{"BearerAuth": []}])
    @participants_blp.arguments(ParticipantCreateSchema)
    @participants_blp.response(200, ParticipantSchema)
    @require_admin
    def put(self, body, token):
        """Update a participant's label."""
        conn = get_db()
        row = conn.execute(
            "SELECT 1 FROM participants WHERE token = ?", (token,)
        ).fetchone()
        if not row:
            conn.close()
            abort(404, message="Participant not found")
        conn.execute(
            "UPDATE participants SET label = ? WHERE token = ?",
            (body["label"], token),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT token, label, created_at FROM participants WHERE token = ?",
            (token,),
        ).fetchone()
        conn.close()
        return dict(updated)

    @participants_blp.doc(security=[{"BearerAuth": []}])
    @participants_blp.response(204)
    @require_admin
    def delete(self, token):
        """Delete a participant (and their response, if any)."""
        conn = get_db()
        row = conn.execute(
            "SELECT 1 FROM participants WHERE token = ?", (token,)
        ).fetchone()
        if not row:
            conn.close()
            abort(404, message="Participant not found")
        conn.execute("DELETE FROM responses WHERE token = ?", (token,))
        conn.execute("DELETE FROM participants WHERE token = ?", (token,))
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# Survey submission
# ---------------------------------------------------------------------------
@survey_blp.route("/submit/<token>")
class SurveySubmit(MethodView):

    @survey_blp.response(200, StatusSchema)
    def post(self, token):
        """Accept and store a survey response."""
        participant = find_participant(token)
        if not participant:
            abort(404, message="Invalid token")

        if is_completed(token):
            abort(409, message="Survey already completed")

        data = request.get_json()
        if not data:
            abort(400, message="No data provided")

        now = datetime.utcnow().isoformat()
        conn = get_db()
        conn.execute(
            "INSERT INTO responses (token, response_data, submitted_at) VALUES (?, ?, ?)",
            (token, json.dumps(data), now),
        )
        conn.commit()
        conn.close()
        return {"status": "ok"}


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------
@responses_blp.route("/responses")
class ResponseList(MethodView):

    @responses_blp.doc(security=[{"BearerAuth": []}])
    @responses_blp.response(200, SurveyResponseSchema(many=True))
    @require_admin
    def get(self):
        """Return all survey responses."""
        conn = get_db()
        rows = conn.execute(
            """
            SELECT r.token, p.label, r.response_data, r.submitted_at
            FROM responses r
            LEFT JOIN participants p ON p.token = r.token
            ORDER BY r.submitted_at
            """
        ).fetchall()
        conn.close()
        return [
            {
                "token": r["token"],
                "label": r["label"],
                "submitted_at": r["submitted_at"],
                "answers": json.loads(r["response_data"]),
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Register blueprints & start
# ---------------------------------------------------------------------------
api.register_blueprint(participants_blp)
api.register_blueprint(survey_blp)
api.register_blueprint(responses_blp)

init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
