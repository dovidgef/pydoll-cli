"""Unit tests for the output formatter."""

from __future__ import annotations

import io
import json

from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import Printer


def test_json_output():
    buf = io.StringIO()
    p = Printer(GlobalOptions(output='json'), stdout=buf)
    p.emit({'a': 1, 'b': [1, 2, 3]})
    parsed = json.loads(buf.getvalue())
    assert parsed == {'a': 1, 'b': [1, 2, 3]}


def test_text_output_of_dict():
    buf = io.StringIO()
    p = Printer(GlobalOptions(output='text'), stdout=buf)
    p.emit({'a': 1, 'b': 'x'})
    assert 'a: 1' in buf.getvalue()
    assert 'b: x' in buf.getvalue()


def test_text_override():
    buf = io.StringIO()
    p = Printer(GlobalOptions(output='text'), stdout=buf)
    p.emit({'path': '/tmp/f.png'}, text='/tmp/f.png')
    assert buf.getvalue().strip() == '/tmp/f.png'
