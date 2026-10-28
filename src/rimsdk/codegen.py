"""Generate rimsdk/_generated.py from a RimMCP tool manifest.

    uv run python -m rimsdk.codegen            # from the live game's /v1/tools (also refreshes manifest.json)
    uv run python -m rimsdk.codegen --bundled  # from the manifest.json snapshot in the package
    uv run python -m rimsdk.codegen --manifest path/to/manifest.json
"""

from __future__ import annotations

import argparse
import json
import keyword
import re
import textwrap
from pathlib import Path
from typing import Any

from .manifest import Manifest, ToolSpec

PACKAGE_DIR = Path(__file__).parent
GENERATED = PACKAGE_DIR / "_generated.py"
SNAPSHOT = PACKAGE_DIR / "manifest.json"


def snake(name: str) -> str:
    out = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()
    return out + "_" if keyword.iskeyword(out) else out


def pascal(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[_\W]+", name) if part)


class Generator:
    def __init__(self, manifest: Manifest):
        self.manifest = manifest
        self.typed_dicts: list[str] = []
        self.typed_dict_names: set[str] = set()

    def type_of(self, schema: dict[str, Any], hint: str) -> str:
        kind = schema.get("type")
        enum = schema.get("enum")
        if enum and kind in ("string", "integer"):
            return "Literal[" + ", ".join(repr(v) for v in enum) + "]"
        if kind == "string":
            return "str"
        if kind == "integer":
            return "int"
        if kind == "number":
            return "float"
        if kind == "boolean":
            return "bool"
        if kind == "array":
            return f"list[{self.type_of(schema.get('items') or {}, hint + 'Item')}]"
        if kind == "object":
            if schema.get("properties"):
                return self.typed_dict(schema, hint)
            return "dict[str, Any]"
        return "Any"

    def typed_dict(self, schema: dict[str, Any], name: str) -> str:
        if name in self.typed_dict_names:
            return name
        self.typed_dict_names.add(name)
        required = set(schema.get("required") or ())
        fields = []
        for key, sub in schema["properties"].items():
            annotation = self.type_of(sub, name + pascal(key))
            fields.append((key, f"Required[{annotation}]" if key in required else annotation, describe(sub)))

        # A field such as `def` can't be a class attribute, so those dicts use the functional form.
        if all(key.isidentifier() and not keyword.iskeyword(key) for key, _, _ in fields):
            lines = [f"class {name}(TypedDict, total=False):"]
            if schema.get("description"):
                lines.append(doc_block(schema["description"], indent="    "))
            for key, annotation, text in fields:
                lines.append(f"    {key}: {annotation}")
                if text:
                    lines.append(doc_block(text, indent="    "))
        else:
            lines = [comment(schema.get("description", ""), "")] if schema.get("description") else []
            lines.append(f"{name} = TypedDict(\n    {name!r},\n    {{")
            for key, annotation, text in fields:
                if text:
                    lines.append(comment(f"{key}: {text}", "        "))
                lines.append(f"        {key!r}: {annotation},")
            lines.append("    },\n    total=False,\n)")
        self.typed_dicts.append("\n".join(lines))
        return name

    def method(self, spec: ToolSpec) -> str:
        schema = spec.input_schema
        props: dict[str, Any] = dict(schema.get("properties") or {})
        required = list(spec.path_params) + [k for k in schema.get("required") or () if k not in spec.path_params]
        for capture in spec.path_params:
            props.setdefault(capture, {"type": "string"})
        optional = [k for k in props if k not in required]

        names = {wire: snake(wire) for wire in props}
        if len(set(names.values())) != len(names):
            raise ValueError(f"{spec.name}: parameter names collide after snake_case conversion: {names}")

        # Only path ids (pawnId, workTypeDefName...) are positional; the schema's required order is
        # arbitrary, so everything else is keyword-only to keep calls unambiguous.
        params = ["self"]
        for wire in spec.path_params:
            params.append(f"{names[wire]}: {self.type_of(props[wire], pascal(spec.name) + pascal(wire))}")
        keyword_required = [w for w in required if w not in spec.path_params]
        if keyword_required or optional:
            params.append("*")
        for wire in keyword_required:
            params.append(f"{names[wire]}: {self.type_of(props[wire], pascal(spec.name) + pascal(wire))}")
        for wire in optional:
            params.append(f"{names[wire]}: {self.type_of(props[wire], pascal(spec.name) + pascal(wire))} | None = None")

        flags = [spec.group or "bridge", "read-only" if spec.read_only else "changes the game"]
        if spec.annotations.get("destructiveHint"):
            flags.append("destructive")
        doc = [textwrap.fill(spec.description, width=92), "", f"[{', '.join(flags)}] {spec.method} {spec.path_template}"]
        if props:
            doc += ["", "Args:"]
            for wire in required + optional:
                text = describe(props[wire]) or "(no description)"
                doc.append(textwrap.fill(f"{names[wire]}: {text}", width=96, initial_indent="    ", subsequent_indent="        "))

        args = ", ".join(f"{wire!r}: {names[wire]}" for wire in required + optional)
        signature = ",\n        ".join(params)
        return (
            f"    def {snake(spec.name)}(\n        {signature},\n    ) -> Result:\n"
            f"{doc_block(chr(10).join(doc), indent='        ', wrap=False)}\n"
            f"        return self._call({spec.name!r}, {{{args}}})\n"
        )

    def render(self) -> str:
        methods = [self.method(spec) for spec in sorted(self.manifest.tools.values(), key=lambda s: s.name)]
        header = (
            f'"""Generated by `python -m rimsdk.codegen` from RimMCP manifest {self.manifest.version}. Do not edit."""\n\n'
            "from __future__ import annotations\n\n"
            "from typing import Any, Literal, Required, TypedDict\n\n"
            "from .result import Result\n\n"
            f"MANIFEST_VERSION = {self.manifest.version!r}\n\n"
        )
        body = "\n\n".join(self.typed_dicts)
        tools = (
            "class GeneratedTools:\n"
            '    """One method per RimMCP tool. Arguments left as None are not sent."""\n\n'
            "    def _call(self, name: str, args: dict[str, Any]) -> Result:\n"
            "        raise NotImplementedError\n\n" + "\n".join(methods)
        )
        return header + (body + "\n\n\n" if body else "") + tools


def describe(schema: dict[str, Any]) -> str:
    text = (schema.get("description") or "").strip()
    bounds = []
    if "minimum" in schema or "maximum" in schema:
        bounds.append(f"range {schema.get('minimum', '')}..{schema.get('maximum', '')}")
    if "maxLength" in schema:
        bounds.append(f"max length {schema['maxLength']}")
    if "maxItems" in schema:
        bounds.append(f"max {schema['maxItems']} items")
    return f"{text} ({'; '.join(bounds)})" if bounds else text


def comment(text: str, indent: str) -> str:
    return textwrap.fill(text, width=100, initial_indent=indent + "# ", subsequent_indent=indent + "# ")


def doc_block(text: str, *, indent: str, wrap: bool = True) -> str:
    """Indent text as a docstring; wrap=False keeps lines the caller already wrapped."""
    if wrap:
        text = "\n".join(textwrap.fill(p, width=100 - len(indent)) for p in text.split("\n"))
    text = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    if "\n" not in text and not text.endswith('"'):
        return f'{indent}"""{text}"""'
    body = "\n".join((indent + line).rstrip() for line in text.split("\n"))
    return f'{indent}"""{body.lstrip()}\n{indent}"""'


def snapshot(data: dict[str, Any]) -> dict[str, Any]:
    """Drop what /v1/tools reports about this session (access preset, per-tool enabled) from a live manifest."""
    data = {k: v for k, v in data.items() if k != "access"}
    data["tools"] = [{k: v for k, v in t.items() if k != "enabled"} for t in data["tools"]]
    return data


def generate(manifest: Manifest) -> str:
    return Generator(manifest).render()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--bundled", action="store_true", help="use the package's manifest.json snapshot")
    source.add_argument("--manifest", type=Path, help="use a manifest JSON file")
    parser.add_argument("--out", type=Path, default=GENERATED)
    args = parser.parse_args(argv)

    if args.manifest:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
    elif args.bundled:
        data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    else:
        from .client import RimClient

        with RimClient.connect() as rim:
            data = snapshot(rim.raw_manifest())
        SNAPSHOT.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")

    manifest = Manifest.from_json(data)
    args.out.write_text(generate(manifest), encoding="utf-8")
    print(f"Wrote {len(manifest.tools)} tools from manifest {manifest.version} to {args.out}")


if __name__ == "__main__":
    main()
