import argparse
import ast
import itertools
import json
import logging
import re
import secrets
from pathlib import Path

from simple_survey.app import create_app


_VARIABLE_REFERENCE_RE = re.compile(r"\{(?P<name>[^{}]+)\}")
_VARIABLE_EQUALITY_RE = re.compile(
    r"""
    \{(?P<name>[^{}]+)\}
    \s*={1,2}(?!=)\s*
    (?P<value>
        "(?:\\.|[^"\\])*"
        |'(?:\\.|[^'\\])*'
        |true\b|false\b|null\b
        |-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _parse_literal(value: str) -> object:
    if value.startswith(("'", '"')):
        return ast.literal_eval(value)

    normalized = value.lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    if normalized == "null":
        return None
    return json.loads(value)


def _find_visible_if_expressions(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "visibleIf" and isinstance(child, str):
                yield child
            else:
                yield from _find_visible_if_expressions(child)
    elif isinstance(value, list):
        for child in value:
            yield from _find_visible_if_expressions(child)


def discover_variable_assignments(
    survey: object,
) -> tuple[list[dict[str, object]], list[str]]:
    values_by_variable: dict[str, list[object]] = {}
    unsupported_expressions: list[str] = []

    for expression in _find_visible_if_expressions(survey):
        matches = list(_VARIABLE_EQUALITY_RE.finditer(expression))
        unmatched_expression = _VARIABLE_EQUALITY_RE.sub("", expression)
        if _VARIABLE_REFERENCE_RE.search(unmatched_expression):
            unsupported_expressions.append(expression)

        for match in matches:
            name = match.group("name").strip()
            value = _parse_literal(match.group("value"))
            values = values_by_variable.setdefault(name, [])
            if value not in values:
                values.append(value)

    if not values_by_variable:
        return [{}], unsupported_expressions

    names = list(values_by_variable)
    assignments = [
        dict(zip(names, values, strict=True))
        for values in itertools.product(*(values_by_variable[name] for name in names))
    ]
    return assignments, unsupported_expressions


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

    try:
        with survey_path.open(encoding="utf-8") as survey_file:
            survey = json.load(survey_file)
    except (OSError, json.JSONDecodeError) as error:
        parser.error(f"could not load survey file: {error}")

    assignments, unsupported_expressions = discover_variable_assignments(survey)
    admin_token = secrets.token_urlsafe(32)
    participants = []
    for variables in assignments:
        participant = {
            "token": secrets.token_urlsafe(32),
            "label": f"Preview participant {json.dumps(variables, ensure_ascii=False)}",
            "variables": variables,
        }
        participants.append(participant)

    app = create_app(
        survey_json_path=str(survey_path),
        participants_seed=participants,
        database_url="sqlite:///:memory:",
        admin_token=admin_token,
    )

    base_url = "http://127.0.0.1:5000"
    print("Survey preview is running with temporary in-memory data.")
    print("Survey participants:")
    for participant in participants:
        variables = json.dumps(participant["variables"], ensure_ascii=False)
        print(f"  {variables}: {base_url}/s/{participant['token']}")
    print(f"API console: {base_url}/docs/")
    print(f"Admin token: {admin_token}")
    for expression in unsupported_expressions:
        print(f"Warning: could not derive all variable values from visibleIf: {expression}")
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