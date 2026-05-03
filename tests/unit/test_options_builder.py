"""Unit tests for options_builder — CLI flags → ChromiumOptions translation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydoll.constants import PageLoadState

from pydoll_cli.context import GlobalOptions
from pydoll_cli.options_builder import build_options


def test_defaults():
    opts = GlobalOptions()
    options = build_options(opts)
    assert options.headless is True
    # pydoll adds --no-first-run / --no-default-browser-check by default via the
    # options manager, which only runs inside Chrome(); we only assert what we set.


def test_all_flags_propagate():
    opts = GlobalOptions(
        browser='chrome',
        headless=False,
        user_data_dir=Path('/tmp/profile'),
        incognito=True,
        proxy='http://user:pass@proxy:8080',
        user_agent='custom-ua',
        accept_languages='en-US,en',
        window_size='1920x1080',
        disable_images=True,
        extra_args=['--no-sandbox'],
        prefs=['profile.password_manager_enabled=false'],
    )
    options = build_options(opts)
    assert options.headless is False
    args = options.arguments
    assert '--user-data-dir=/tmp/profile' in args
    assert '--incognito' in args
    assert '--proxy-server=http://user:pass@proxy:8080' in args
    assert '--user-agent=custom-ua' in args
    assert '--window-size=1920,1080' in args
    assert '--no-sandbox' in args
    prefs = options.browser_preferences
    assert prefs['profile']['password_manager_enabled'] is False
    assert prefs['profile']['managed_default_content_settings']['images'] == 2


def test_bad_pref_raises():
    opts = GlobalOptions(prefs=['not_a_pair'])
    with pytest.raises(ValueError, match='KEY=VALUE'):
        build_options(opts)


def test_window_size_bad_shape_silently_ignored():
    opts = GlobalOptions(window_size='invalid')
    options = build_options(opts)
    assert not any('--window-size=' in a for a in options.arguments)


def test_no_sandbox_not_added_by_default():
    options = build_options(GlobalOptions())
    assert '--no-sandbox' not in options.arguments
    assert '--disable-dev-shm-usage' not in options.arguments


def test_in_container_adds_sandbox_bypass():
    options = build_options(GlobalOptions(in_container=True))
    assert '--no-sandbox' in options.arguments
    assert '--disable-dev-shm-usage' in options.arguments


def test_proxy_insecure_adds_ignore_cert_errors():
    options = build_options(GlobalOptions(proxy_insecure=True))
    assert '--ignore-certificate-errors' in options.arguments


def test_proxy_insecure_off_by_default():
    options = build_options(GlobalOptions())
    assert '--ignore-certificate-errors' not in options.arguments


def test_proxy_insecure_does_not_duplicate():
    options = build_options(
        GlobalOptions(
            proxy_insecure=True,
            extra_args=['--ignore-certificate-errors'],
        ),
    )
    assert options.arguments.count('--ignore-certificate-errors') == 1


def test_webrtc_leak_protection_propagates():
    options = build_options(GlobalOptions(webrtc_leak_protection=True))
    assert options.webrtc_leak_protection is True


def test_webrtc_leak_protection_off_by_default():
    options = build_options(GlobalOptions())
    assert options.webrtc_leak_protection is False


def test_page_load_state_interactive():
    options = build_options(GlobalOptions(page_load_state='interactive'))
    assert options.page_load_state == PageLoadState.INTERACTIVE


def test_page_load_state_complete_default():
    options = build_options(GlobalOptions())
    assert options.page_load_state == PageLoadState.COMPLETE


def test_browser_binary_overrides_kind(tmp_path: Path):
    fake = tmp_path / 'chrome'
    fake.write_text('')
    opts = GlobalOptions(browser='wavebox', browser_binary=fake)
    options = build_options(opts)
    assert options.binary_location == str(fake)
