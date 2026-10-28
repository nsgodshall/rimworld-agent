"""`rimagent inspect`: read-only access to the live game for whoever is fixing the code.

    uv run python -m rimagent inspect --tools                  # the read-only tools
    uv run python -m rimagent inspect --doc check_placement    # one tool's description and arguments
    uv run python -m rimagent inspect list_pawns detail=full   # call it: wire (camelCase) names, JSON values
    uv run python -m rimagent inspect get_map_view x=100 z=120 width=40 height=40
"""

from __future__ import annotations

import json
import sys
from typing import Any

from rimsdk import RimClient, errors
from rimsdk.manifest import Manifest


def parse_value(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


def main(args: list[str], focus_wait: float) -> int:
    manifest = Manifest.bundled()
    read_tools = {n: t for n, t in sorted(manifest.tools.items()) if t.read_only}
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if args[0] == "--tools":
        for name, tool in read_tools.items():
            print(f"{name:28} {tool.description.split('. ')[0][:110]}")
        return 0
    if args[0] == "--doc":
        tool = manifest.tools[args[1]]
        print(f"{tool.name} ({'read-only' if tool.read_only else 'changes the game: not callable here'})\n{tool.description}\n")
        print(json.dumps(tool.input_schema.get("properties", {}), indent=1))
        return 0

    name, pairs = args[0], args[1:]
    if name not in read_tools:
        print(f"{name} is not a read-only tool. Changes go through managers, applied by the runtime.", file=sys.stderr)
        return 2
    call_args = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        call_args[key] = parse_value(value)
    max_chars = int(call_args.pop("maxChars", 30000))
    with RimClient.connect(read_only=True, focus_wait=focus_wait) as rim:
        try:
            result = rim.call(name, **call_args)
        except errors.RimError as exc:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    text = json.dumps(result, indent=1)
    print(text[:max_chars] + (f"\n... truncated {len(text) - max_chars} chars (pass maxChars=N)" if len(text) > max_chars else ""))
    return 0
