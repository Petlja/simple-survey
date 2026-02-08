import os
import json
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, jsonify, abort as flask_abort
from flask.views import MethodView
from flask_smorest import Api, Blueprint, abort
from marshmallow import Schema, fields

from simple_survey.models import db, Participant, Response


def create_app(
    survey_json_path: str | None = None,
    participants_seed_path: str | None = None,
    **config_overrides,
) -> Flask:
    """Application factory.

    Parameters
    ----------
    survey_json_path:
        Absolute path to the survey definition JSON file.
        Defaults to ``survey.json`` in the current working directory.
    participants_seed_path:
        Absolute path to the participants seed JSON file.
        Defaults to ``participants.json`` in the current working directory.
    **config_overrides:
        Extra Flask config values (e.g. ``SQLALCHEMY_DATABASE_URI``).
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

    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL",
        "sqlite:///" + str(cwd / "survey.db"),
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

    # Apply overrides ---------------------------------------------------------
    app.config.update(config_overrides)

    db.init_app(app)

    ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------
    def load_survey_json():
        with open(survey_json_path, "r") as f:
            return json.load(f)

    def find_participant(token):
        p = db.session.get(Participant, token)
        if p:
            return {"token": p.token, "label": p.label}
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
        count = db.session.query(Participant).count()
        if count == 0 and os.path.exists(participants_seed_path):
            with open(participants_seed_path, "r") as f:
                seed = json.load(f)["participants"]
            for p in seed:
                existing = db.session.get(Participant, p["token"])
                if not existing:
                    db.session.add(Participant(token=p["token"], label=p["label"]))
            db.session.commit()

    def is_completed(token):
        return db.session.query(Response).filter_by(token=token).first() is not None

    # -----------------------------------------------------------------------
    # Marshmallow schemas
    # -----------------------------------------------------------------------
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

        previous_answers = None
        if is_completed(token):
            resp = db.session.query(Response).filter_by(token=token).first()
            if resp:
                previous_answers = resp.response_data

        return render_template(
            "survey.html",
            token=token,
            survey_json=json.dumps(load_survey_json()),
            already_completed=is_completed(token),
            previous_answers=previous_answers,
        )

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
                    "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
                    "answers": json.loads(r.response_data),
                }
                for r, label in rows
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
