# Simple Survey

A lightweight Flask survey application using [SurveyJS](https://surveyjs.io/).
Each participant receives a unique token link to submit their response.

## Features

- Token-based survey access (one response per participant)
- Option to update a previously submitted response
- Survey defined in `survey.json` (SurveyJS format)
- SQLAlchemy ORM with support for SQLite, PostgreSQL, and MS SQL Server
- REST API with Swagger UI documentation
- Admin endpoints secured with a bearer token
- Managed with uv and installable as a dependency via Git

## Project Structure

```
simple-survey/
├── pyproject.toml          # Project and dependency definition
├── .env.example            # Environment configuration template
├── survey-sample.json      # Sample survey definition (SurveyJS format)
├── participants.json       # Seed file for initial participants
├── docker-compose.yml      # Local MS SQL Server for development
└── simple_survey/
    ├── __init__.py         # Exports create_app()
    ├── app.py              # Flask application factory
    ├── models.py           # SQLAlchemy models
    └── templates/          # Jinja2 HTML templates
```

---

## Running directly from this repo

### 1. Install dependencies

Install the package and all development dependencies. uv creates the `.venv`
virtual environment automatically:

```bash
uv sync
```

### 2. Configure environment variables

Create a local `.env` file from the committed template, then adjust it as
described in [Configuration](#configuration):

```bash
cp .env.example .env
cp survey-sample.json survey.json
```

### 3. Run the app

```bash
# Option A: Using the Flask CLI
uv run --env-file .env flask --app simple_survey run

# Option B: Using gunicorn (production)
uv run --env-file .env gunicorn "simple_survey:create_app()"
```

The app resolves relative survey and participant file paths from the current
working directory.

### 4. Access

- Survey page: `http://localhost:5000/s/<participant-token>`
- Swagger UI: `http://localhost:5000/docs/`

---

## Using as a package in a deployment repo

If you need a deployment repo for Azure or another Git-based deployment,
include the following files:

### Repo structure

```
survey-deploy/
├── pyproject.toml
├── uv.lock
├── app.py
├── survey.json
└── participants.json
```

### Dependencies

Tag a release in this repo (`git tag v0.1.0 && git push origin v0.1.0`),
then initialize the deployment project and add the tagged package:

```bash
uv init --bare
uv add "simple-survey @ git+https://github.com/YOUR_USER/simple-survey.git@v0.1.0"
uv add "pymssql>=2.2" "gunicorn>=22.0"
```

### app.py

```python
from simple_survey import create_app

app = create_app()
```

### Running

```bash
uv run gunicorn app:app
```

For Azure App Service, set `DATABASE_URL` and `ADMIN_TOKEN` as
Application settings and use `uv run gunicorn app:app` as the startup command.

### Upgrading

Update the package tag and redeploy:

```bash
uv add "simple-survey @ git+https://github.com/YOUR_USER/simple-survey.git@v0.2.0"
```

---

## Configuration

Copy `.env.example` to `.env` and customize it, or set the same variables in
your environment. The run commands above load `.env` with `--env-file .env`.
File paths may be relative to the current working directory or absolute.

| Variable                 | Description                                              |
| ------------------------ | -------------------------------------------------------- |
| `ADMIN_TOKEN`            | Bearer token for admin API endpoints                     |
| `DATABASE_URL`           | Database connection string (default: `sqlite:///survey.db`) |
| `SURVEY_JSON_PATH`       | Survey JSON path, relative to the working directory or absolute (default: `survey.json`) |
| `PARTICIPANTS_SEED_PATH` | Participant seed path, relative to the working directory or absolute (default: `participants.json`) |

### Database driver extras

```bash
# PostgreSQL
uv sync --extra postgres

# MS SQL Server
uv sync --extra mssql

# Production server
uv sync --extra prod
```

## API Docs

Swagger UI is available at `/docs/` when the app is running.
