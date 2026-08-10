import ast
import itertools
import json
import logging
import re
import secrets
import socket
from pathlib import Path

import click
from werkzeug.serving import ThreadedWSGIServer

from simple_survey.app import create_app


class _ExclusiveThreadedWSGIServer(ThreadedWSGIServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


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


@click.command(help="Run a survey locally with temporary preview data.")
@click.argument(
    "survey_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("survey.json"),
    required=False,
)
@click.option(
    "-p",
    "--port",
    type=int,
    default=5000,
    show_default=True,
    help="Port to serve on.",
)
def main(survey_file: Path, port: int) -> None:
    try:
        with survey_file.open(encoding="utf-8") as survey_stream:
            survey = json.load(survey_stream)
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(f"could not load survey file: {error}") from error

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
        survey_json_path=str(survey_file),
        participants_seed=participants,
        database_url="sqlite:///:memory:",
        admin_token=admin_token,
    )

    logging.getLogger("werkzeug").addFilter(
        lambda r: "This is a development server" not in r.getMessage()
    )
    with _ExclusiveThreadedWSGIServer("127.0.0.1", port, app) as server:
        base_url = f"http://127.0.0.1:{port}"
        click.echo("Survey preview is running with temporary in-memory data.")
        click.echo("Survey participants:")
        for participant in participants:
            variables = json.dumps(participant["variables"], ensure_ascii=False)
            click.echo(f"  {variables}: {base_url}/s/{participant['token']}")
        click.echo(f"API console: {base_url}/docs/")
        click.echo(f"Admin token: {admin_token}")
        for expression in unsupported_expressions:
            click.echo(
                "Warning: could not derive all variable values from visibleIf: "
                f"{expression}"
            )
        click.echo("Open the survey URL to submit a response.")
        click.echo("Open the API console and authorize with the admin token.")
        click.echo("Use its API operations to manage participants and inspect responses.")
        click.echo("Press Ctrl+C to stop; all preview data will be discarded.")

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()