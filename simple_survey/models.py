import uuid
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Participant(db.Model):
    __tablename__ = "participants"

    token = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    label = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    response = db.relationship("Response", back_populates="participant", uselist=False, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "token": self.token,
            "label": self.label,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Response(db.Model):
    __tablename__ = "responses"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    token = db.Column(db.String(36), db.ForeignKey("participants.token"), nullable=False, unique=True)
    response_data = db.Column(db.Text, nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    participant = db.relationship("Participant", back_populates="response")
