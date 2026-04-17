"""Unit tests for extractor schema loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydoll.extractor import ExtractionModel

from pydoll_cli import extractor_loader


def test_json_schema_builds_model(tmp_path: Path):
    spec = {
        'name': 'Quote',
        'fields': {
            'text': {'selector': '.text'},
            'author': {'selector': '.author'},
            'tags': {'selector': '.tag', 'list': True},
            'year': {'selector': '.year', 'type': 'int', 'optional': True},
        },
    }
    p = tmp_path / 'quote.json'
    p.write_text(json.dumps(spec))
    model = extractor_loader.load(p)
    assert issubclass(model, ExtractionModel)
    fields = model.model_fields
    assert set(fields.keys()) == {'text', 'author', 'tags', 'year'}
    # Optional field has None default
    assert fields['year'].default is None


def test_json_schema_requires_fields(tmp_path: Path):
    p = tmp_path / 'bad.json'
    p.write_text(json.dumps({'name': 'X'}))
    with pytest.raises(ValueError, match='fields'):
        extractor_loader.load(p)


def test_python_schema_loads_single_class(tmp_path: Path):
    p = tmp_path / 'schema.py'
    p.write_text(
        'from pydoll.extractor import ExtractionModel, Field\n'
        'class Quote(ExtractionModel):\n'
        '    text: str = Field(selector=".text")\n'
    )
    model = extractor_loader.load(p)
    assert issubclass(model, ExtractionModel)
    assert model.__name__ == 'Quote'


def test_python_schema_multiple_classes_requires_disambiguation(tmp_path: Path):
    p = tmp_path / 'schema.py'
    p.write_text(
        'from pydoll.extractor import ExtractionModel, Field\n'
        'class A(ExtractionModel):\n'
        '    x: str = Field(selector=".a")\n'
        'class B(ExtractionModel):\n'
        '    y: str = Field(selector=".b")\n'
    )
    with pytest.raises(ValueError, match='Multiple'):
        extractor_loader.load(p)
    chosen = extractor_loader.load(p, class_name='B')
    assert chosen.__name__ == 'B'


def test_unsupported_suffix(tmp_path: Path):
    p = tmp_path / 'schema.yaml'
    p.write_text('x: 1')
    with pytest.raises(ValueError, match='Unsupported'):
        extractor_loader.load(p)
