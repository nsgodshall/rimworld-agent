"""ClaudeEscalator: on a halting incident, a headless Claude Code session fixes the colony's code.

The session gets the incident report and this repo. It may edit only the managers and tests, and
reads the game only through `rimagent inspect` and dry runs, so the runtime stays the only thing
that changes the game. Its answer is checked: the test suite must pass before play resumes.
"""

from __future__ import annotations

import difflib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .incidents import Incident, Resolution

REPO = Path(__file__).resolve().parents[2]
EDITABLE = ("src/rimagent/managers", "tests")

ALLOWED_TOOLS = [
    "Read(./**)", "Glob", "Grep",
    *(f"Edit(./{path}/**)" for path in EDITABLE),
    *(f"Write(./{path}/**)" for path in EDITABLE),
    "Bash(uv run pytest:*)",
    "Bash(uv run python -m rimagent inspect:*)",
    "Bash(uv run python -m rimagent run --dry-run:*)",
]

RESOLUTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["resume", "halt"]},
        "summary": {"type": "string", "description": "What you found and changed, in two or three sentences."},
        "files": {"type": "array", "items": {"type": "string"}, "description": "Files you created or edited."},
    },
    "required": ["action", "summary", "files"],
}

PROMPT = """\
The RimWorld colony runtime has paused the game and stopped on an incident it couldn't handle.
The report is {report}; read it first, then CLAUDE.md for how the runtime and managers work.

Change the colony's code so the runtime handles this situation from now on:
- Edit or add managers in src/rimagent/managers/ (and tests in tests/). Nothing else is editable;
  if the real fix needs the runtime or SDK changed, say so and answer "halt".
- You can't change the game yourself. Read it with `uv run python -m rimagent inspect ...`; the runtime
  applies your managers when it resumes. {event_note}
- Never guess the shape of a reply: inspect a real one before your code (or FakeRim) relies on a field.
- Before answering "resume", run `uv run python -m rimagent run --dry-run` to see the changes your
  code would make in the live game, and `uv run pytest -q`, which must pass.
- Answer "halt" when the situation needs a person (a decision, a missing capability, a risky change).
"""

EVENT_NOTE = (
    "The event that triggered this ({kind}) will be delivered again to your code right after "
    "resuming, and it is still going on in the game: handle the current situation, not just future ones."
)


class ClaudeEscalator:
    def __init__(
        self,
        *,
        claude: str = "claude",
        model: str | None = None,
        budget_usd: float = 3.0,
        timeout_s: float = 1800,
        verify: list[str] | None = None,
        repo: Path = REPO,
    ):
        self.claude = shutil.which(claude) or claude
        self.model = model
        self.budget_usd = budget_usd
        self.timeout_s = timeout_s
        self.verify = verify if verify is not None else ["uv", "run", "pytest", "-q"]
        self.repo = repo

    def command(self, prompt: str) -> list[str]:
        cmd = [
            self.claude, "-p", prompt,
            "--output-format", "json",
            "--json-schema", json.dumps(RESOLUTION_SCHEMA),
            "--permission-mode", "dontAsk",
            "--allowedTools", *ALLOWED_TOOLS,
            "--max-budget-usd", str(self.budget_usd),
        ]
        if self.model:
            cmd += ["--model", self.model]
        return cmd

    def escalate(self, incident: Incident, report: Path) -> Resolution:
        stem = report.with_suffix("")
        note = EVENT_NOTE.format(kind=incident.event.kind) if incident.event else ""
        prompt = PROMPT.format(report=report.resolve().relative_to(self.repo) if report.is_absolute() else report, event_note=note)
        before = self._sources()
        try:
            proc = subprocess.run(self.command(prompt), cwd=self.repo, capture_output=True, text=True, timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            return Resolution(False, f"The fixing session ran past {self.timeout_s:.0f}s.")
        except OSError as exc:
            return Resolution(False, f"Couldn't start Claude Code ({self.claude}): {exc}")

        output = _parse(proc.stdout)
        Path(f"{stem}.session.json").write_text(json.dumps(output or {"stdout": proc.stdout, "stderr": proc.stderr}, indent=1))
        diff = self._diff(before, self._sources())
        Path(f"{stem}.diff").write_text(diff)
        details: dict[str, Any] = {
            "cost_usd": (output or {}).get("total_cost_usd"),
            "session_id": (output or {}).get("session_id"),
            "diff": f"{stem}.diff",
            # Tool calls the sandbox refused: a sign the fix wanted more than managers and tests.
            "denied": [d.get("tool_name") for d in (output or {}).get("permission_denials") or []],
        }
        answer = _answer(output)
        if answer is None:
            return Resolution(False, f"The fixing session gave no usable answer (exit {proc.returncode}).", details)
        details["files"] = answer.get("files", [])
        if answer["action"] != "resume":
            return Resolution(False, answer["summary"], details)

        check = subprocess.run(self.verify, cwd=self.repo, capture_output=True, text=True)
        if check.returncode != 0:
            Path(f"{stem}.verify.txt").write_text(check.stdout + check.stderr)
            return Resolution(False, f"Fix proposed but `{' '.join(self.verify)}` fails: {answer['summary']}", details)
        return Resolution(True, answer["summary"], details)

    def _sources(self) -> dict[str, str]:
        files = {}
        for root in EDITABLE:
            for path in sorted((self.repo / root).rglob("*.py")):
                files[str(path.relative_to(self.repo))] = path.read_text(encoding="utf-8")
        return files

    @staticmethod
    def _diff(before: dict[str, str], after: dict[str, str]) -> str:
        chunks = []
        for name in sorted(set(before) | set(after)):
            a, b = before.get(name, ""), after.get(name, "")
            if a != b:
                chunks.extend(difflib.unified_diff(a.splitlines(True), b.splitlines(True), f"a/{name}", f"b/{name}"))
        return "".join(chunks)


def _parse(stdout: str) -> dict[str, Any] | None:
    try:
        value = json.loads(stdout)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _answer(output: dict[str, Any] | None) -> dict[str, Any] | None:
    """The structured answer: `structured_output` when --json-schema took, else JSON in the result text."""
    if not output:
        return None
    answer = output.get("structured_output")
    if answer is None and isinstance(output.get("result"), str):
        text = output["result"].strip()
        start, end = text.find("{"), text.rfind("}")
        answer = _parse(text[start:end + 1]) if start != -1 else None
    if not isinstance(answer, dict) or answer.get("action") not in ("resume", "halt"):
        return None
    answer.setdefault("summary", "")
    return answer
