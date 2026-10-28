"""`uv run python -m rimsdk`: check the connection to RimWorld and the SDK's fit to the running mod."""

from __future__ import annotations

import json
import sys

from . import MANIFEST_VERSION, RimClient, config, errors


def main() -> int:
    found = config.discover()
    print(f"bridge  {found.url}  (token from {found.source}{'' if found.token else ', none found'})")
    with RimClient.connect(read_only=True) as rim:
        try:
            report(rim)
        except errors.RimError as exc:
            print(f"error   {type(exc).__name__}: {exc}")
            return 1
    return 0


def report(rim: RimClient) -> None:
    print(f"health  {json.dumps(rim.health())}")
    drift = rim.check_manifest()
    print(f"sdk     manifest {MANIFEST_VERSION}: " + (f"DRIFT {drift}" if drift else "matches the running mod"))
    off = sorted(set(rim.manifest.tools) - rim.enabled_tools())
    print(f"access  {len(rim.manifest.tools) - len(off)} tools on" + (f", off: {', '.join(off)}" if off else ""))
    context = rim.get_game_context()
    print(f"game    tick {context.tick}, map {context.map_id}")
    print(json.dumps(context.data, indent=1)[:2000])


if __name__ == "__main__":
    sys.exit(main())
