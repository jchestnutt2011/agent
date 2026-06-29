import importlib
import pkgutil

import tools


def load_tools():
    """Discover modules in tools/, each exposing SCHEMA (dict) and run(**kwargs).

    Returns (schemas, dispatch) where schemas is the list to pass to the model
    and dispatch maps tool name -> callable.
    """
    schemas = []
    dispatch = {}

    for _, module_name, _ in pkgutil.iter_modules(tools.__path__):
        module = importlib.import_module(f"tools.{module_name}")
        if not hasattr(module, "SCHEMA") or not hasattr(module, "run"):
            continue
        schema = module.SCHEMA
        name = schema["function"]["name"]
        schemas.append(schema)
        dispatch[name] = module.run

    return schemas, dispatch
