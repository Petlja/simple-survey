# Simple Survey

A lightweight Flask application for creating and distributing surveys using [SurveyJS](https://surveyjs.io/). Each participant receives a unique token link to submit their response.

## Features

- Token-based survey access (one response per participant)
- Survey defined in `survey.json` (SurveyJS format)
- SQLAlchemy ORM with support for SQLite and PostgreSQL
- REST API with Swagger UI documentation
- Admin endpoints secured with a bearer token

## Setup

```bash
pip install -r requirements.txt
```

## Running

```bash
export ADMIN_TOKEN="your-secret-token"
flask run
```

The app will be available at `http://localhost:5000`.

## Configuration

| Variable | Description |
|---|---|
| `ADMIN_TOKEN` | Bearer token for admin API endpoints |
| `DATABASE_URL` | Database connection string (default: `sqlite:///survey.db`) |

### Database examples

```bash
# SQLite (default)
export DATABASE_URL="sqlite:///survey.db"

# PostgreSQL
export DATABASE_URL="postgresql://user:password@localhost:5432/survey"
```

## API Docs

Swagger UI is available at `/docs/` when the app is running.

## Project Structure

- `app.py` — Flask application with API endpoints
- `models.py` — SQLAlchemy database models
- `survey.json` — Survey definition (SurveyJS format)
- `participants.json` — Seed file for initial participants
- `templates/` — HTML templates for survey and thank-you pages
