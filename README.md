# Simple Survey

A lightweight Flask survey application using [SurveyJS](https://surveyjs.io/).
Each participant receives a unique token link to submit their response.

## Features

- Token-based survey access (one response per participant)
- Per-participant SurveyJS variables stored as a JSON object
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
├── participants.example.json # Empty participant seed example
├── docker-compose.yml      # Local MS SQL Server for development
└── simple_survey/
    ├── __init__.py         # Exports create_app()
    ├── app.py              # Flask application factory
    ├── cli.py              # Local survey preview command
    ├── models.py           # SQLAlchemy models
    └── templates/          # Jinja2 HTML templates
```

---

## Run as the `survey-preview` CLI tool

After installing the package, preview a survey without configuring a database,
admin token, or participant file:

```bash
survey-preview [survey-file]
```

When running from this repository, use:

```bash
uv run survey-preview [survey-file]
```

The survey file defaults to `survey.json`. The command creates temporary
in-memory data and generates an admin token. It scans every `visibleIf` in the
survey for literal variable comparisons such as `{group} = 1`, creates a preview
participant for each discovered variable-value combination, and prints each
participant's survey URL. Authorize in the API console with the printed admin
token to manage participants and inspect responses. All preview data is
discarded when the command stops.

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
cp participants.example.json participants.json
```

`participants.json` is ignored by Git because participant tokens grant access
to view and update that participant's response. Add development participants to
the local copy, or create them through the admin API after starting the app.

Each participant can define a `variables` object whose entries are assigned with
SurveyJS `setVariable` before the survey is rendered:

```json
{
    "token": "00000000-0000-0000-0000-000000000000",
    "label": "Example participant",
    "variables": {
        "group": 1,
        "lessonId": 42
    }
}
```

Survey definitions can reference these values in expressions such as
`{group} = 1`. The sample survey assigns pages 1-4 to group `1` and pages 5-8
to group `2`. The participant create and update API operations accept
the same `variables` object and return it in participant responses.

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
└── survey.json
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

For Azure App Service, set `DATABASE_URL` and `ADMIN_TOKEN` as Application
settings and use `uv run gunicorn app:app` as the startup command. Create
participants after deployment through the admin API. If initial seeding is
required instead, provide an environment-specific file through deployment-managed
storage and set `PARTICIPANTS_SEED_PATH` to its path; do not commit that file.

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
| `PARTICIPANTS_SEED_PATH` | Untracked or deployment-managed participant seed path (default: `participants.json`; absent files are skipped) |

## Participant token security

Participant tokens are bearer credentials: a token holder can open the survey,
view an existing response, and submit an update. Keep production tokens out of
source control and use different tokens in each environment.

If tokens are committed, rotate the affected participants in every deployed
database and send new links. Removing the file from a later commit does not
invalidate existing database records or remove the values from Git history.

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
