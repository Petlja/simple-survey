import os
import json
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, jsonify, abort as flask_abort
from flask.views import MethodView
from flask_smorest import Api, Blueprint, abort
from marshmallow import Schema, fields
from sqlalchemy import inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from simple_survey.models import db, Participant, ParticipantQuestion, Response


def create_app(
    survey_json_path: str | None = None,
    participants_seed_path: str | None = None,
    database_url: str | None = None,
    admin_token: str | None = None,
    participants_seed: list[dict[str, object]] | None = None,
) -> Flask:
    """Application factory.

    Parameters
    ----------
    survey_json_path:
        Path to the survey definition JSON file. Relative paths use the
        current working directory. Defaults to the ``SURVEY_JSON_PATH``
        environment variable, then ``survey.json``.
    participants_seed_path:
        Path to the participants seed JSON file. Relative paths use the
        current working directory. Defaults to the ``PARTICIPANTS_SEED_PATH``
        environment variable, then ``participants.json``.
    database_url:
        Database connection string. Defaults to the ``DATABASE_URL``
        environment variable, then ``sqlite:///survey.db``.
    admin_token:
        Bearer token for admin API endpoints. Defaults to the ``ADMIN_TOKEN``
        environment variable.
    participants_seed:
        Participants to seed directly instead of reading the seed file.
    """
    app = Flask(__name__)

    # Defaults ----------------------------------------------------------------
    cwd = Path.cwd()
    survey_json_path = survey_json_path or os.environ.get(
        "SURVEY_JSON_PATH", str(cwd / "survey.json")
    )
    participants_seed_path = participants_seed_path or os.environ.get(
        "PARTICIPANTS_SEED_PATH", str(cwd / "participants.json")
    )

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        database_url
        if database_url is not None
        else os.environ.get("DATABASE_URL", "sqlite:///" + str(cwd / "survey.db"))
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Flask-Smorest -----------------------------------------------------------
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

    db.init_app(app)

    ADMIN_TOKEN = (
        admin_token if admin_token is not None else os.environ.get("ADMIN_TOKEN", "")
    )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------
    def load_survey_json():
        with open(survey_json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def find_participant(token):
        p = db.session.get(Participant, token)
        if p:
            return p.to_dict()
        return None

    def require_admin(f):
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
        db.create_all()
        # Databases created by older versions lack these columns.
        added_response_columns = {
            "status": "VARCHAR(16) NOT NULL DEFAULT 'submitted'",
            "last_page": "INTEGER",
            "version": "VARCHAR(64)",
        }
        response_columns = {c["name"] for c in inspect(db.engine).get_columns("responses")}
        with db.engine.begin() as conn:
            for name, ddl in added_response_columns.items():
                if name not in response_columns:
                    # SQL Server rejects the optional COLUMN keyword.
                    conn.execute(text(f"ALTER TABLE responses ADD {name} {ddl}"))
        count = db.session.query(Participant).count()
        seed = participants_seed
        if seed is None and os.path.exists(participants_seed_path):
            with open(participants_seed_path, "r", encoding="utf-8") as f:
                seed = json.load(f)["participants"]
        if count == 0 and seed:
            for p in seed:
                existing = db.session.get(Participant, p["token"])
                if not existing:
                    db.session.add(
                        Participant(
                            token=p["token"],
                            label=p["label"],
                            variables=p.get("variables", {}),
                        )
                    )
            db.session.commit()

    def is_completed(token):
        return (
            db.session.query(Response).filter_by(token=token, status="submitted").first()
            is not None
        )

    def parse_write_body():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            abort(400, message="Body must be a JSON object")
        answers = body.get("answers")
        if not isinstance(answers, dict):
            abort(400, message="answers must be a JSON object")
        expected_version = body.get("expected_version")
        if expected_version is not None and not isinstance(expected_version, str):
            abort(400, message="expected_version must be a string or null")
        new_version = body.get("new_version")
        if not isinstance(new_version, str) or not 0 < len(new_version) <= 64:
            abort(400, message="new_version must be a non-empty string of at most 64 characters")
        return body, answers, expected_version, new_version

    def reject_conflict(token, expected_version, new_version):
        db.session.rollback()
        participant = db.session.get(Participant, token)
        stored = db.session.query(Response.version).filter_by(token=token).scalar()
        # The token grants survey access, so it is not logged.
        app.logger.warning(
            "Write conflict on %s for participant %r: expected version %r, stored %r, rejected %r",
            request.path.rsplit("/", 1)[0],
            participant.label if participant else None,
            expected_version,
            stored,
            new_version,
        )
        abort(409, message="Answers were changed in another window")

    def record_participant_questions(token, answers):
        """Store when each answer key (question name) first appeared for the participant."""
        known = set(
            db.session.scalars(
                select(ParticipantQuestion.question_name).where(ParticipantQuestion.token == token)
            )
        )
        now = datetime.now(timezone.utc)
        for name in answers:
            if name not in known:
                db.session.add(
                    ParticipantQuestion(token=token, question_name=name, first_answered_at=now)
                )

    def write_response(token, expected_version, insert_values, update_values, answers):
        """Write only if the stored version equals expected_version; abort 409 otherwise."""
        version_matches = (
            Response.version.is_(None)
            if expected_version is None
            else Response.version == expected_version
        )
        result = db.session.execute(
            update(Response)
            .where(Response.token == token, version_matches)
            .values(**update_values)
        )
        if result.rowcount == 0:
            if expected_version is not None:
                reject_conflict(token, expected_version, update_values["version"])
            db.session.add(Response(token=token, **insert_values))
            try:
                db.session.flush()
            except IntegrityError:
                reject_conflict(token, expected_version, insert_values["version"])
        record_participant_questions(token, answers)
        db.session.commit()

    # -----------------------------------------------------------------------
    # Marshmallow schemas
    # -----------------------------------------------------------------------
    class ParticipantSchema(Schema):
        token = fields.String(metadata={"format": "uuid"})
        label = fields.String(required=True)
        variables = fields.Dict()
        created_at = fields.String(metadata={"format": "date-time"})

    class ParticipantCreateSchema(Schema):
        label = fields.String(required=True)
        variables = fields.Dict(required=False)

    class SurveyResponseSchema(Schema):
        token = fields.String()
        label = fields.String()
        status = fields.String(metadata={"enum": ["draft", "submitted"]})
        last_page = fields.Integer(allow_none=True)
        submitted_at = fields.String(metadata={"format": "date-time"})
        answers = fields.Dict()

    class ParticipantQuestionSchema(Schema):
        token = fields.String()
        label = fields.String()
        question_name = fields.String()
        first_answered_at = fields.String(metadata={"format": "date-time"})

    class ErrorSchema(Schema):
        error = fields.String()

    class StatusSchema(Schema):
        status = fields.String()

    # -----------------------------------------------------------------------
    # Non-API routes
    # -----------------------------------------------------------------------
    @app.route("/")
    def home():
        return "<h1>Simple Survey</h1>"

    @app.route("/s/<token>")
    def survey_page(token):
        participant = find_participant(token)
        if not participant:
            flask_abort(404)

        resp = db.session.query(Response).filter_by(token=token).first()

        page = render_template(
            "survey.html",
            token=token,
            survey_json=json.dumps(load_survey_json()),
            survey_variables=participant["variables"],
            already_completed=resp is not None and resp.status == "submitted",
            previous_answers=json.loads(resp.response_data) if resp else None,
            last_page=resp.last_page if resp and resp.status == "draft" else None,
            version=resp.version if resp else None,
        )
        # The Back button would otherwise show cached answers and a version from an earlier visit.
        return page, {"Cache-Control": "no-store"}

    @app.route("/thank-you")
    def thank_you():
        return render_template("thank_you.html")

    # -----------------------------------------------------------------------
    # API Blueprints
    # -----------------------------------------------------------------------
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

    # -- Participants --------------------------------------------------------
    @participants_blp.route("/")
    class ParticipantList(MethodView):

        @participants_blp.doc(security=[{"BearerAuth": []}])
        @participants_blp.response(200, ParticipantSchema(many=True))
        @require_admin
        def get(self):
            rows = db.session.query(Participant).order_by(Participant.created_at).all()
            return [p.to_dict() for p in rows]

        @participants_blp.doc(security=[{"BearerAuth": []}])
        @participants_blp.arguments(ParticipantCreateSchema)
        @participants_blp.response(201, ParticipantSchema)
        @require_admin
        def post(self, body):
            p = Participant(
                label=body["label"],
                variables=body.get("variables", {}),
            )
            db.session.add(p)
            db.session.commit()
            return p.to_dict()

    @participants_blp.route("/<token>")
    class ParticipantItem(MethodView):

        @participants_blp.doc(security=[{"BearerAuth": []}])
        @participants_blp.response(200, ParticipantSchema)
        @require_admin
        def get(self, token):
            p = db.session.get(Participant, token)
            if not p:
                abort(404, message="Participant not found")
            return p.to_dict()

        @participants_blp.doc(security=[{"BearerAuth": []}])
        @participants_blp.arguments(ParticipantCreateSchema)
        @participants_blp.response(200, ParticipantSchema)
        @require_admin
        def put(self, body, token):
            p = db.session.get(Participant, token)
            if not p:
                abort(404, message="Participant not found")
            p.label = body["label"]
            if "variables" in body:
                p.variables = body["variables"]
            db.session.commit()
            return p.to_dict()

        @participants_blp.doc(security=[{"BearerAuth": []}])
        @participants_blp.response(204)
        @require_admin
        def delete(self, token):
            p = db.session.get(Participant, token)
            if not p:
                abort(404, message="Participant not found")
            db.session.delete(p)
            db.session.commit()

    # -- Survey submission ---------------------------------------------------
    @survey_blp.route("/submit/<token>")
    class SurveySubmit(MethodView):

        @survey_blp.response(200, StatusSchema)
        def post(self, token):
            participant = find_participant(token)
            if not participant:
                abort(404, message="Invalid token")

            _, answers, expected_version, new_version = parse_write_body()
            values = {
                "response_data": json.dumps(answers),
                "status": "submitted",
                "version": new_version,
                "submitted_at": datetime.now(timezone.utc),
            }
            write_response(token, expected_version, values, values, answers)
            return {"status": "ok"}

    @survey_blp.route("/save/<token>")
    class SurveySave(MethodView):

        @survey_blp.response(200, StatusSchema)
        def post(self, token):
            """Save answers without requiring all required questions; keeps current status."""
            participant = find_participant(token)
            if not participant:
                abort(404, message="Invalid token")

            body, answers, expected_version, new_version = parse_write_body()
            page = body.get("page")
            if page is not None and (type(page) is not int or page < 0):
                abort(400, message="page must be a non-negative integer")

            values = {
                "response_data": json.dumps(answers),
                "last_page": page,
                "version": new_version,
                "submitted_at": datetime.now(timezone.utc),
            }
            write_response(token, expected_version, {**values, "status": "draft"}, values, answers)
            return {"status": "ok"}

    # -- Responses -----------------------------------------------------------
    @responses_blp.route("/responses")
    class ResponseList(MethodView):

        @responses_blp.doc(security=[{"BearerAuth": []}])
        @responses_blp.response(200, SurveyResponseSchema(many=True))
        @require_admin
        def get(self):
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
                    "status": r.status,
                    "last_page": r.last_page,
                    "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
                    "answers": json.loads(r.response_data),
                }
                for r, label in rows
            ]

    @responses_blp.route("/participant-questions")
    class ParticipantQuestionList(MethodView):

        @responses_blp.doc(security=[{"BearerAuth": []}])
        @responses_blp.response(200, ParticipantQuestionSchema(many=True))
        @require_admin
        def get(self):
            rows = (
                db.session.query(ParticipantQuestion, Participant.label)
                .outerjoin(Participant, ParticipantQuestion.token == Participant.token)
                .order_by(ParticipantQuestion.first_answered_at, ParticipantQuestion.id)
                .all()
            )
            return [
                {
                    "token": q.token,
                    "label": label,
                    "question_name": q.question_name,
                    "first_answered_at": q.first_answered_at.isoformat(),
                }
                for q, label in rows
            ]

    # -----------------------------------------------------------------------
    # Register blueprints & init DB
    # -----------------------------------------------------------------------
    _api = Api(app)
    _api.register_blueprint(participants_blp)
    _api.register_blueprint(survey_blp)
    _api.register_blueprint(responses_blp)

    with app.app_context():
        init_db()

    return app
