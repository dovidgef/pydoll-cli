"""`install-skill` — drop the bundled Claude Code skill into ~/.claude/skills/.

The skill file (``SKILL.md``) is shipped inside the wheel at
``pydoll_cli/_skill/SKILL.md`` via a hatchling ``force-include`` rule in
``pyproject.toml``. This command copies it to a Claude Code skills directory so
users who installed the package (rather than cloning the repo) can get the
skill with one command.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Annotated

import typer

from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import EXIT_GENERIC, Printer

_SKILL_NAME = 'pydoll-cli'


def _bundled_skill_text() -> str | None:
    """Return the bundled SKILL.md text, or None if it isn't shipped.

    The wheel build copies ``.claude/skills/pydoll-cli/SKILL.md`` to
    ``pydoll_cli/_skill/SKILL.md``. In editable installs that file may be
    absent; in that case fall back to the in-repo path so ``uv run`` works
    during development too.
    """
    try:
        bundled = files('pydoll_cli').joinpath('_skill/SKILL.md')
        if bundled.is_file():
            return bundled.read_text(encoding='utf-8')
    except (FileNotFoundError, ModuleNotFoundError, AttributeError):
        pass

    # Editable / development fallback: walk up from this file to the repo root.
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / '.claude' / 'skills' / _SKILL_NAME / 'SKILL.md'
        if candidate.is_file():
            return candidate.read_text(encoding='utf-8')
    return None


_VALID_SCOPES = ('project', 'user')


def _skills_dir_for_scope(scope: str) -> Path:
    """Resolve the Claude Code skills directory for the given scope.

    Per the Claude Code skill docs, skills live at:
      - project scope: <cwd>/.claude/skills/<name>/SKILL.md  (this repo only)
      - user scope:    ~/.claude/skills/<name>/SKILL.md      (every Claude Code session)
    """
    if scope == 'project':
        return Path.cwd() / '.claude' / 'skills'
    if scope == 'user':
        return Path.home() / '.claude' / 'skills'
    raise ValueError(f'unknown scope: {scope!r}')


def register(app: typer.Typer) -> None:
    @app.command(
        'install-skill',
        help=(
            'Install the pydoll-cli Claude Code skill at project (./.claude/skills, '
            'default) or user (~/.claude/skills) scope.'
        ),
        epilog=(
            'Examples:\n'
            '  pydoll-cli install-skill                    # ./.claude/skills/pydoll-cli/SKILL.md\n'
            '  pydoll-cli install-skill --scope user       # ~/.claude/skills/pydoll-cli/SKILL.md\n'
            '  pydoll-cli install-skill --target ./some/dir  # explicit skills dir\n'
            '  pydoll-cli install-skill --force\n'
            '  pydoll-cli --output json install-skill\n'
        ),
    )
    def _cmd(
        ctx: typer.Context,
        scope: Annotated[
            str,
            typer.Option(
                '--scope',
                help=(
                    "'project' installs to ./.claude/skills (this repo only); "
                    "'user' installs to ~/.claude/skills (every Claude Code session). "
                    'Ignored when --target is given.'
                ),
                case_sensitive=False,
            ),
        ] = 'project',
        target: Annotated[
            Path | None,
            typer.Option(
                '--target',
                help=(
                    'Explicit skills directory. Overrides --scope. The skill is '
                    'written to <target>/pydoll-cli/SKILL.md.'
                ),
            ),
        ] = None,
        force: Annotated[
            bool,
            typer.Option(
                '--force',
                '-f',
                help='Overwrite an existing SKILL.md at the destination.',
            ),
        ] = False,
    ) -> None:
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)

        scope_lc = scope.lower()
        if scope_lc not in _VALID_SCOPES:
            raise typer.BadParameter(
                f'--scope must be one of: {", ".join(_VALID_SCOPES)} (got {scope!r})',
            )

        text = _bundled_skill_text()
        if text is None:
            raise printer.fatal(
                'SKILL.md not found in this pydoll-cli install. Reinstall via '
                "'uv tool install --force git+https://github.com/dovidgef/pydoll-cli' "
                '(or the pipx/pip equivalent).',
                EXIT_GENERIC,
            )

        if target is not None:
            skills_dir = target.expanduser()
            scope_resolved = 'custom'
        else:
            skills_dir = _skills_dir_for_scope(scope_lc)
            scope_resolved = scope_lc
        dest_dir = skills_dir / _SKILL_NAME
        dest = dest_dir / 'SKILL.md'

        already_exists = dest.exists()
        if already_exists and not force:
            raise printer.fatal(
                f'{dest} already exists. Re-run with --force to overwrite.',
                EXIT_GENERIC,
            )

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding='utf-8')

        printer.emit(
            {
                'path': str(dest),
                'scope': scope_resolved,
                'overwritten': already_exists,
                'bytes': len(text.encode('utf-8')),
            },
            text=f'installed skill ({scope_resolved}) to {dest}',
        )
