import inspect
import typing

from rimsdk import RimClient
from rimsdk.codegen import GENERATED, generate, snake
from rimsdk.manifest import Manifest


def test_generated_module_matches_bundled_manifest():
    # Fails when _generated.py was edited by hand or manifest.json changed without regenerating.
    assert GENERATED.read_text(encoding="utf-8") == generate(Manifest.bundled()), (
        "Run: uv run python -m rimsdk.codegen --bundled"
    )


def test_every_tool_has_a_method_with_resolvable_hints():
    for name in Manifest.bundled().tools:
        method = getattr(RimClient, snake(name))
        typing.get_type_hints(method)


def test_methods_send_wire_names(rim, fake):
    """Calling each method with every parameter must hand each value to the bridge under its wire name."""
    manifest = Manifest.bundled()
    for name, tool in manifest.tools.items():
        method = getattr(rim, snake(name))
        props = dict(tool.input_schema.get("properties", {}))
        for capture in tool.path_params:
            props.setdefault(capture, {"type": "string"})
        kwargs = {snake(wire): f"v-{wire}" for wire in props}
        fake.requests.clear()
        method(**kwargs)
        (_, path, body) = fake.requests[0]
        for wire in props:
            sent = (body or {}).get(wire) == f"v-{wire}" or f"v-{wire}" in path
            assert sent, f"{name}: {wire} was not sent"


def test_only_path_ids_are_positional_and_other_required_args_are_keyword_only():
    for name, spec in Manifest.bundled().tools.items():
        params = list(inspect.signature(getattr(RimClient, snake(name))).parameters.values())[1:]
        positional = [p.name for p in params if p.kind is p.POSITIONAL_OR_KEYWORD]
        assert positional == [snake(k) for k in spec.path_params], name
        for wire in spec.input_schema.get("required", []):
            if wire not in spec.path_params:
                p = next(p for p in params if p.name == snake(wire))
                assert p.kind is p.KEYWORD_ONLY and p.default is p.empty, f"{name}.{wire}"
