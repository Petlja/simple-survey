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
- Packaged with Poetry — installable as a dependency via git

## Project Structure

```
simple-survey/
├── pyproject.toml          # Poetry package definition
├── survey.json             # Survey definition (SurveyJS format)
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

### 1. Create virtual environment and install dependencies

Create virtual environment for this project. We suggest to use `.venv` subdirectory to place virtual environment.

Activate your virtual environment.

If you don't have Poetry installed, install it in your virtual environment:

```bash
pip install poetry
```

Install the package and all dev dependencies:

```bash
poetry install
```

### 2. Configure environment variables

Create a `.env` file in the project root:

```dotenv
ADMIN_TOKEN=your-secret-token
# DATABASE_URL defaults to sqlite:///survey.db if not set
# DATABASE_URL=mssql+pymssql://user:pass@localhost:1433/survey
```

Or set appropriate environment variables other way.

### 3. Run the app

Ensure your virtual environment is activated, then:

```bash
# Option A: Using Flask CLI
FLASK_APP=simple_survey flask run

# Option B: Using gunicorn (production)
gunicorn "simple_survey:create_app()"
```

The app will look for `survey.json` and `participants.json` in the
current working directory. You can override these paths with environment
variables:

```dotenv
SURVEY_JSON_PATH=/absolute/path/to/survey.json
PARTICIPANTS_SEED_PATH=/absolute/path/to/participants.json
```

### 4. Access

- Survey page: `http://localhost:5000/s/<participant-token>`
- Swagger UI: `http://localhost:5000/docs/`

---

## Using as a package in a deployment repo

If you need a deployment repo to Azure or other deployment from Git, put th following files in the repo:

### Repo structure

```
survey-deploy/
├── requirements.txt
├── app.py
├── survey.json
└── participants.json
```

### requirements.txt

Tag a release in this repo (`git tag v0.1.0 && git push origin v0.1.0`),
then reference it:

```txt
simple-survey @ git+https://github.com/YOUR_USER/simple-survey.git@v0.1.0
pymssql>=2.2
gunicorn>=22.0
```

### app.py

```python
from simple_survey import create_app

app = create_app()
```

### Running

```bash
gunicorn app:app
```

For Azure App Service, set `DATABASE_URL` and `ADMIN_TOKEN` as
Application settings and use `gunicorn app:app` as the startup command.

### Upgrading

Update the tag in `requirements.txt` and redeploy.

---

## Configuration

| Variable                 | Description                                              |
| ------------------------ | -------------------------------------------------------- |
| `ADMIN_TOKEN`            | Bearer token for admin API endpoints                     |
| `DATABASE_URL`           | Database connection string (default: `sqlite:///survey.db`) |
| `SURVEY_JSON_PATH`       | Path to survey JSON file (default: `./survey.json`)      |
| `PARTICIPANTS_SEED_PATH` | Path to participants seed file (default: `./participants.json`) |

### Database driver extras

```bash
# PostgreSQL
poetry install -E postgres

# MS SQL Server
poetry install -E mssql

# Production server
poetry install -E prod
```

## API Docs

Swagger UI is available at `/docs/` when the app is running.
