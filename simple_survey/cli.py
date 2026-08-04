import argparse
import logging
import secrets
from pathlib import Path

from simple_survey.app import create_app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="survey-preview",
        description="Run a survey locally with temporary preview data.",
    )
    parser.add_argument(
        "survey_file",
        nargs="?",
        default="survey.json",
        help="survey JSON file (default: survey.json)",
    )
    args = parser.parse_args(argv)

    survey_path = Path(args.survey_file)
    if not survey_path.is_file():
        parser.error(f"survey file not found: {survey_path}")

    admin_token = secrets.token_urlsafe(32)
    participant_token = secrets.token_urlsafe(32)
    app = create_app(
        survey_json_path=str(survey_path),
        participants_seed=[
            {"token": participant_token, "label": "Preview participant"}
        ],
        database_url="sqlite:///:memory:",
        admin_token=admin_token,
    )

    base_url = "http://127.0.0.1:5000"
    print("Survey preview is running with temporary in-memory data.")
    print(f"Survey:      {base_url}/s/{participant_token}")
    print(f"API console: {base_url}/docs/")
    print(f"Admin token: {admin_token}")
    print("Open the survey URL to submit a response.")
    print("Open the API console and authorize with the admin token.")
    print("Use its API operations to manage participants and inspect responses.")
    print("Press Ctrl+C to stop; all preview data will be discarded.")

    logging.getLogger("werkzeug").addFilter(
        lambda r: "This is a development server" not in r.getMessage()
    )
    app.run(host="127.0.0.1", port=5000, use_reloader=False)


if __name__ == "__main__":
    main()