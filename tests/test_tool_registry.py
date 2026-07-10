"""Validates every chat tool actually discovered from tools/*.py — not a fake
temp directory, the real thing. This is the safety net from
tools/CONTRIBUTING.md's checklist: a malformed SCHEMA (missing a required
field, a name that doesn't match its own dispatch entry, wrong types) should
fail here loudly instead of silently breaking tool-calling against the local
model or getting caught only by chance in manual testing."""

import inspect

from tool_registry import load_tools


def test_load_tools_returns_at_least_one_tool():
    schemas, dispatch = load_tools()
    assert len(schemas) > 0
    assert len(dispatch) > 0


def test_every_schema_has_valid_function_calling_shape():
    schemas, _ = load_tools()
    for schema in schemas:
        assert schema.get("type") == "function", schema
        function = schema.get("function")
        assert isinstance(function, dict), schema

        name = function.get("name")
        assert isinstance(name, str) and name, f"missing/empty name: {schema}"

        description = function.get("description")
        assert isinstance(description, str) and description, f"missing/empty description for '{name}'"

        parameters = function.get("parameters")
        assert isinstance(parameters, dict), f"missing parameters for '{name}'"
        assert parameters.get("type") == "object", f"parameters.type must be 'object' for '{name}'"

        properties = parameters.get("properties", {})
        assert isinstance(properties, dict), f"parameters.properties must be a dict for '{name}'"

        required = parameters.get("required", [])
        assert isinstance(required, list), f"parameters.required must be a list for '{name}'"
        for arg in required:
            assert arg in properties, f"'{name}' requires '{arg}' but never declares it in properties"


def test_no_duplicate_tool_names():
    schemas, _ = load_tools()
    names = [schema["function"]["name"] for schema in schemas]
    assert len(names) == len(set(names)), f"duplicate tool names: {names}"


def test_every_schema_name_has_a_matching_dispatch_entry():
    schemas, dispatch = load_tools()
    for schema in schemas:
        name = schema["function"]["name"]
        assert name in dispatch, f"'{name}' has a schema but no dispatch entry"
        assert callable(dispatch[name]), f"dispatch['{name}'] is not callable"


def test_schemas_and_dispatch_are_one_to_one():
    schemas, dispatch = load_tools()
    assert len(schemas) == len(dispatch)


def test_every_declared_parameter_is_a_valid_json_schema_property():
    """Catches the most common copy-paste mistake: a property missing its
    own "type", which the model needs to know how to fill in the argument."""
    schemas, _ = load_tools()
    for schema in schemas:
        name = schema["function"]["name"]
        properties = schema["function"]["parameters"].get("properties", {})
        for prop_name, prop_schema in properties.items():
            assert isinstance(prop_schema, dict), f"'{name}.{prop_name}' schema must be a dict"
            assert "type" in prop_schema, f"'{name}.{prop_name}' is missing a 'type'"


def test_every_run_function_accepts_its_declared_parameters():
    """If SCHEMA promises an argument, run() needs to actually accept it —
    otherwise a real tool call from the model raises a TypeError at the
    worst possible time (mid-conversation) instead of failing here."""
    schemas, dispatch = load_tools()
    for schema in schemas:
        name = schema["function"]["name"]
        properties = schema["function"]["parameters"].get("properties", {})
        required = schema["function"]["parameters"].get("required", [])
        run_fn = dispatch[name]
        sig = inspect.signature(run_fn)
        accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())

        if accepts_kwargs:
            continue
        for arg in properties:
            assert arg in sig.parameters, f"'{name}' SCHEMA declares '{arg}' but run() doesn't accept it"
