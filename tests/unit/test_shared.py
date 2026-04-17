"""Unit tests for the URL/selector argument normalizer."""

from __future__ import annotations

import pytest

from pydoll_cli.commands._shared import (
    _normalize_url_selector,
    _normalize_url_selector_text,
    looks_like_url,
)


@pytest.mark.parametrize(
    'value,expected',
    [
        ('https://example.com', True),
        ('http://x', True),
        ('file:///tmp/a.html', True),
        ('about:blank', True),
        ('chrome://settings', True),
        ('data:text/html,<p>', True),
        ('h1', False),
        ('#id', False),
        ('.class', False),
        ('input[name="q"]', False),
        ('', False),
        (None, False),
    ],
)
def test_looks_like_url(value, expected):
    assert looks_like_url(value) is expected


class TestNormalizeUrlSelector:
    def test_both_given_passthrough(self):
        assert _normalize_url_selector('https://x.com', 'h1') == ('https://x.com', 'h1')

    def test_real_url_no_selector(self):
        # User gave URL only; selector empty (will error downstream as "missing").
        assert _normalize_url_selector('https://x.com', '') == ('https://x.com', '')

    def test_bare_selector_shifts(self):
        # With --session, user typed only a selector; typer parked it in `url`.
        assert _normalize_url_selector('h1', '') == (None, 'h1')

    def test_bare_selector_compound(self):
        assert _normalize_url_selector('input[name="q"]', '') == (None, 'input[name="q"]')

    def test_no_args_unchanged(self):
        assert _normalize_url_selector(None, '') == (None, '')


class TestNormalizeUrlSelectorText:
    def test_all_three_given(self):
        assert _normalize_url_selector_text('https://x.com', '#sel', 'hi') == (
            'https://x.com',
            '#sel',
            'hi',
        )

    def test_selector_text_only_shifts(self):
        # --session user: "tabs.py type '#sel' 'hi'" → typer: url='#sel', sel='hi', text=''
        assert _normalize_url_selector_text('#sel', 'hi', '') == (None, '#sel', 'hi')

    def test_real_url_then_selector_text(self):
        assert _normalize_url_selector_text('https://x.com', '#sel', 'hi') == (
            'https://x.com',
            '#sel',
            'hi',
        )

    def test_missing_selector_no_shift(self):
        # If URL looks like URL but no selector, nothing to shift.
        assert _normalize_url_selector_text('https://x.com', '', '') == (
            'https://x.com',
            '',
            '',
        )
