"""Test-suite-wide setup.

Pin Rich's rendering environment before anything imports typer.

Typer renders `--help` through Rich, and Rich's option highlighter styles a
flag by splitting the leading dash into its own span. With colour enabled
`--level` comes out as ``\\x1b[1;36m-\\x1b[0m\\x1b[1;36m-level\\x1b[0m``, so the
literal substring the help tests assert on is never present. Locally there is
no TTY and Rich stays plain; CI hands the process ``FORCE_COLOR``, which flips
Rich into terminal mode and the same tests fail there and only there.

Neutralising the colour signals here (rather than per test) keeps every current
and future help assertion checking the text a user reads. ``COLUMNS`` is pinned
too so the options table never wraps a long flag across two lines.
"""

from __future__ import annotations

import os

for _var in ('FORCE_COLOR', 'CLICOLOR_FORCE', 'CLICOLOR'):
    os.environ.pop(_var, None)

os.environ['TERM'] = 'dumb'
os.environ['NO_COLOR'] = '1'
os.environ['COLUMNS'] = '200'
