import base64
import secrets
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Participant(db.Model):
    __tablename__ = "participants"

    token = db.Column(
        db.String(64),
        primary_key=True,
        default=lambda: base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii"),
    )
    label = db.Column(db.String(255), nullable=False)
    variables = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    response = db.relationship("Response", back_populates="participant", uselist=False, cascade="all, delete-orphan")
    participant_questions = db.relationship("ParticipantQuestion", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "token": self.token,
            "label": self.label,
            "variables": self.variables,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Response(db.Model):
    __tablename__ = "responses"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    token = db.Column(db.String(64), db.ForeignKey("participants.token"), nullable=False, unique=True)
    response_data = db.Column(db.Text, nullable=False)
    # "draft" until first submit; later saves keep "submitted" and may lack required answers.
    status = db.Column(db.String(16), nullable=False, server_default="submitted")
    # Zero-based index among visible SurveyJS pages.
    last_page = db.Column(db.Integer, nullable=True)
    # Browser-proposed id of the last write; a write must name it to prevent overwriting another window.
    version = db.Column(db.String(64), nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    participant = db.relationship("Participant", back_populates="response")


class ParticipantQuestion(db.Model):
    """When a question name first appeared in a participant's saved answers."""

    __tablename__ = "participant_questions"
    __table_args__ = (db.UniqueConstraint("token", "question_name"),)

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    token = db.Column(db.String(64), db.ForeignKey("participants.token"), nullable=False)
    question_name = db.Column(db.String(255), nullable=False)
    first_answered_at = db.Column(db.DateTime, nullable=False)
