"""Load a pydoll `ExtractionModel` from either a Python file or a JSON schema.

Python file (`schema.py`)
    Must contain at least one subclass of `pydoll.extractor.ExtractionModel`.
    If multiple are present, pass ``--schema-class NAME`` to disambiguate.

JSON schema (`schema.json`)
    Declarative form — we synthesise a Pydantic model at runtime::

        {
          "name": "Quote",
          "fields": {
            "text":   {"selector": ".text"},
            "author": {"selector": ".author"},
            "tags":   {"selector": ".tag", "list": true},
            "year":   {"selector": ".year", "type": "int", "optional": true}
          }
        }
"""

from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path
from typing import Any

from pydantic import create_model
from pydantic_core import PydanticUndefined
from pydoll.extractor import ExtractionModel, Field

_SCALAR_TYPES: dict[str, type] = {
    'str': str,
    'string': str,
    'int': int,
    'integer': int,
    'float': float,
    'number': float,
    'bool': bool,
    'boolean': bool,
}


def load(path: Path, class_name: str | None = None) -> type[ExtractionModel]:
    """Load an ExtractionModel from a .py or .json file."""
    if path.suffix.lower() == '.json':
        return _from_json(path)
    if path.suffix.lower() == '.py':
        return _from_python(path, class_name)
    raise ValueError(f'Unsupported schema file type: {path.suffix!r}. Use .py or .json.')


# ---- Python file --------------------------------------------------------


def _from_python(path: Path, class_name: str | None) -> type[ExtractionModel]:
    spec = importlib.util.spec_from_file_location(f'_pydoll_cli_schema_{path.stem}', path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Could not load schema module from {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    candidates: list[type[ExtractionModel]] = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, ExtractionModel) and obj is not ExtractionModel:
            candidates.append(obj)

    if not candidates:
        raise ValueError(f'No subclass of ExtractionModel found in {path}')

    if class_name:
        for cls in candidates:
            if cls.__name__ == class_name:
                return cls
        raise ValueError(
            f'{class_name!r} not found in {path}. Available: '
            + ', '.join(c.__name__ for c in candidates),
        )

    if len(candidates) > 1:
        names = ', '.join(c.__name__ for c in candidates)
        raise ValueError(
            f'Multiple ExtractionModel subclasses in {path} ({names}); '
            f'disambiguate with --schema-class NAME.',
        )

    return candidates[0]


# ---- JSON declarative form ----------------------------------------------


def _from_json(path: Path) -> type[ExtractionModel]:
    spec = json.loads(path.read_text(encoding='utf-8'))
    name = spec.get('name') or path.stem.title().replace('_', '')
    fields_spec = spec.get('fields')
    if not isinstance(fields_spec, dict) or not fields_spec:
        raise ValueError(f'JSON schema at {path} must have a non-empty "fields" object.')

    pydantic_fields: dict[str, Any] = {}
    for fname, raw in fields_spec.items():
        if not isinstance(raw, dict):
            raise ValueError(f'Field {fname!r} must be an object.')
        py_type, default = _json_field_type(raw)
        field_info = Field(
            selector=raw.get('selector'),
            attribute=raw.get('attribute'),
            description=raw.get('description'),
            default=default,
        )
        pydantic_fields[fname] = (py_type, field_info)

    model = create_model(name, __base__=ExtractionModel, **pydantic_fields)
    return model


def _json_field_type(raw: dict[str, Any]) -> tuple[Any, Any]:
    """Resolve (python_type, default) for a JSON schema field."""
    type_name = (raw.get('type') or 'str').lower()
    base = _SCALAR_TYPES.get(type_name)
    if base is None:
        raise ValueError(f'Unsupported type: {type_name!r}')

    is_list = bool(raw.get('list', False))
    is_optional = bool(raw.get('optional', False))

    py_type: Any = list[base] if is_list else base  # type: ignore[valid-type]
    if is_optional:
        py_type = py_type | None
        default: Any = raw.get('default')
    else:
        default = raw.get('default', PydanticUndefined)
    return py_type, default
