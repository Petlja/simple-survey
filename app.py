import os
import json
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, render_template, request, jsonify, abort as flask_abort
from flask.views import MethodView
from flask_smorest import Api, Blueprint, abort
from marshmallow import Schema, fields

from models import db, Participant, Response

app = Flask(__name__)

# Database URL: set DATABASE_URL env var for PostgreSQL, defaults to SQLite
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(os.path.dirname(__file__), "survey.db"),
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

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


def find_participant(token):
    """Find a participant by token in the database."""
    p = db.session.get(Participant, token)
    if p:
        return {"token": p.token, "label": p.label}
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
    db.create_all()
    # Seed from participants.json if the table is empty and the file exists
    count = db.session.query(Participant).count()
    if count == 0 and os.path.exists(PARTICIPANTS_SEED_PATH):
        with open(PARTICIPANTS_SEED_PATH, "r") as f:
            seed = json.load(f)["participants"]
        for p in seed:
            existing = db.session.get(Participant, p["token"])
            if not existing:
                db.session.add(Participant(token=p["token"], label=p["label"]))
        db.session.commit()


def is_completed(token):
    """Check if a participant has already submitted a response."""
    return db.session.query(Response).filter_by(token=token).first() is not None


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

    previous_answers = None
    if is_completed(token):
        resp = db.session.query(Response).filter_by(token=token).first()
        if resp:
            previous_answers = resp.response_data  # already a JSON string

    return render_template(
        "survey.html",
        token=token,
        survey_json=json.dumps(load_survey_json()),
        already_completed=is_completed(token),
        previous_answers=previous_answers,
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
        rows = db.session.query(Participant).order_by(Participant.created_at).all()
        return [p.to_dict() for p in rows]

    @participants_blp.doc(security=[{"BearerAuth": []}])
    @participants_blp.arguments(ParticipantCreateSchema)
    @participants_blp.response(201, ParticipantSchema)
    @require_admin
    def post(self, body):
        """Create a new participant."""
        p = Participant(label=body["label"])
        db.session.add(p)
        db.session.commit()
        return p.to_dict()


@participants_blp.route("/<token>")
class ParticipantItem(MethodView):

    @participants_blp.doc(security=[{"BearerAuth": []}])
    @participants_blp.response(200, ParticipantSchema)
    @require_admin
    def get(self, token):
        """Get a single participant by token."""
        p = db.session.get(Participant, token)
        if not p:
            abort(404, message="Participant not found")
        return p.to_dict()

    @participants_blp.doc(security=[{"BearerAuth": []}])
    @participants_blp.arguments(ParticipantCreateSchema)
    @participants_blp.response(200, ParticipantSchema)
    @require_admin
    def put(self, body, token):
        """Update a participant's label."""
        p = db.session.get(Participant, token)
        if not p:
            abort(404, message="Participant not found")
        p.label = body["label"]
        db.session.commit()
        return p.to_dict()

    @participants_blp.doc(security=[{"BearerAuth": []}])
    @participants_blp.response(204)
    @require_admin
    def delete(self, token):
        """Delete a participant (and their response, if any)."""
        p = db.session.get(Participant, token)
        if not p:
            abort(404, message="Participant not found")
        db.session.delete(p)
        db.session.commit()


# ---------------------------------------------------------------------------
# Survey submission
# ---------------------------------------------------------------------------
@survey_blp.route("/submit/<token>")
class SurveySubmit(MethodView):

    @survey_blp.response(200, StatusSchema)
    def post(self, token):
        """Accept and store a survey response (or update an existing one)."""
        participant = find_participant(token)
        if not participant:
            abort(404, message="Invalid token")

        data = request.get_json()
        if not data:
            abort(400, message="No data provided")

        existing = db.session.query(Response).filter_by(token=token).first()
        if existing:
            existing.response_data = json.dumps(data)
            existing.submitted_at = datetime.now(timezone.utc)
        else:
            r = Response(token=token, response_data=json.dumps(data))
            db.session.add(r)
        db.session.commit()
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
        rows = (
            db.session.query(Response, Participant.label)
            .outerjoin(Participant, Response.token == Participant.token)
            .order_by(Response.submitted_at)
            .all()
        )
        return [
            {
                "token": r.token,
                "label": label,
                "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
                "answers": json.loads(r.response_data),
            }
            for r, label in rows
        ]


# ---------------------------------------------------------------------------
# Register blueprints & start
# ---------------------------------------------------------------------------
api.register_blueprint(participants_blp)
api.register_blueprint(survey_blp)
api.register_blueprint(responses_blp)

with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
