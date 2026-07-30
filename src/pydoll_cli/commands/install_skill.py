"""`install-skill` — drop the bundled Claude Code skill into a skills dir.

The skill (``SKILL.md`` plus ``references/*.md``) is shipped inside the wheel
at ``pydoll_cli/_skill/`` via a hatchling ``force-include`` rule in
``pyproject.toml``. This command copies it to a Claude Code skills directory so
users who installed the package (rather than cloning the repo) can get the
skill with one command.
"""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from importlib.abc import Traversable

from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import EXIT_GENERIC, Printer

_SKILL_NAME = 'pydoll-cli'


def _collect_md_files(root: Traversable) -> list[tuple[str, str]]:
    """Return (relative_path, text) for every .md file under a skill root.

    ``root`` is either a ``Path`` or an ``importlib.resources`` Traversable
    (which may live inside a zip), so only the Traversable API is used.
    """
    out: list[tuple[str, str]] = []

    def walk(node: Traversable, prefix: str) -> None:
        for child in node.iterdir():
            rel = f'{prefix}{child.name}'
            if child.is_dir():
                walk(child, f'{rel}/')
            elif child.name.endswith('.md'):
                out.append((rel, child.read_text(encoding='utf-8')))

    walk(root, '')
    return sorted(out)


def _bundled_skill_files() -> list[tuple[str, str]] | None:
    """Return the bundled skill files, or None if they aren't shipped.

    The wheel build copies ``.claude/skills/pydoll-cli/`` to
    ``pydoll_cli/_skill/``. In editable installs that directory may be absent;
    in that case fall back to the in-repo path so ``uv run`` works during
    development too.
    """
    try:
        bundled = files('pydoll_cli').joinpath('_skill')
        if bundled.joinpath('SKILL.md').is_file():
            return _collect_md_files(bundled)
    except (FileNotFoundError, ModuleNotFoundError, AttributeError):
        pass

    # Editable / development fallback: walk up from this file to the repo root.
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / '.claude' / 'skills' / _SKILL_NAME
        if (candidate / 'SKILL.md').is_file():
            return _collect_md_files(candidate)
    return None


_VALID_SCOPES = ('project', 'user')


def _user_config_dir() -> Path:
    """Claude Code's user config directory.

    Defaults to ``~/.claude``, but ``CLAUDE_CONFIG_DIR`` relocates the whole
    config tree — skills included. Honouring it matters: writing to
    ``~/.claude/skills`` on a machine that sets the override installs the skill
    somewhere Claude Code never reads, and the command still reports success.
    """
    override = os.environ.get('CLAUDE_CONFIG_DIR')
    if override:
        return Path(override).expanduser()
    return Path.home() / '.claude'


def _skills_dir_for_scope(scope: str) -> Path:
    """Resolve the Claude Code skills directory for the given scope.

    Per the Claude Code skill docs, skills live at:
      - project scope: <cwd>/.claude/skills/<name>/SKILL.md  (this repo only)
      - user scope:    <config dir>/skills/<name>/SKILL.md   (every Claude Code
        session; the config dir is ``~/.claude`` unless ``CLAUDE_CONFIG_DIR``
        says otherwise)
    """
    if scope == 'project':
        return Path.cwd() / '.claude' / 'skills'
    if scope == 'user':
        return _user_config_dir() / 'skills'
    raise ValueError(f'unknown scope: {scope!r}')


def register(app: typer.Typer) -> None:
    @app.command(
        'install-skill',
        help=(
            'Install the pydoll-cli Claude Code skill at project (./.claude/skills, '
            'default) or user (the Claude Code config dir) scope.'
        ),
        epilog=(
            'Examples:\n'
            '  pydoll-cli install-skill                    # ./.claude/skills/pydoll-cli/\n'
            '  pydoll-cli install-skill --scope user       # <config dir>/skills/pydoll-cli/\n'
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
                    "'user' installs to the Claude Code config dir (every session) — "
                    '~/.claude/skills, or $CLAUDE_CONFIG_DIR/skills when set. '
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
                    'written to <target>/pydoll-cli/.'
                ),
            ),
        ] = None,
        force: Annotated[
            bool,
            typer.Option(
                '--force',
                '-f',
                help='Overwrite an existing skill at the destination.',
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

        skill_files = _bundled_skill_files()
        if not skill_files:
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

        total_bytes = 0
        for rel, text in skill_files:
            out_path = dest_dir / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text, encoding='utf-8')
            total_bytes += len(text.encode('utf-8'))

        printer.emit(
            {
                'path': str(dest),
                'scope': scope_resolved,
                'overwritten': already_exists,
                'files': [rel for rel, _ in skill_files],
                'bytes': total_bytes,
            },
            text=(f'installed skill ({scope_resolved}) to {dest_dir} ({len(skill_files)} files)'),
        )
