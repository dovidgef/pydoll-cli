"""`keyboard` subcommand group — dispatch keyboard events page-wide.

Distinct from `type SELECTOR TEXT` (which targets a specific input). Use
this for global hotkeys (Ctrl+S, F12), modifier+key combos, or text entry
into a focused element after a `click`.
"""

from __future__ import annotations

from typing import Annotated

import typer
from pydoll.constants import Key
from pydoll.protocol.input.types import KeyModifier

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer

# Accept both the pydoll `KeyModifier` name (CTRL) and the more common spelling
# (CONTROL) on the CLI; map both to the same enum.
_MODIFIER_ALIASES: dict[str, str] = {
    'CONTROL': 'CTRL',
    'CMD': 'META',
    'COMMAND': 'META',
    'OPT': 'ALT',
    'OPTION': 'ALT',
}

group_app = typer.Typer(
    help='Page-level keyboard input (press, hotkey, type, key down/up).',
    no_args_is_help=True,
    rich_markup_mode='rich',
)


def _resolve_key(name: str) -> Key:
    """Map a CLI key name (e.g. ENTER, control, a) to a pydoll Key enum value."""
    upper = name.upper().replace('-', '_')
    try:
        return Key[upper]
    except KeyError as e:
        raise CliError(
            f'unknown key {name!r}. Use a name from pydoll.constants.Key (e.g. ENTER, '
            'TAB, ARROW_DOWN, CONTROL, F1).',
            exit_code=2,
        ) from e


def _resolve_modifiers(spec: str | None) -> int | None:
    """Map a comma-separated modifier spec ("CONTROL,SHIFT") to a CDP modifier int.

    pydoll's KeyModifier is an IntEnum (ALT=1, CTRL=2, META=4, SHIFT=8); the
    CDP wire value is the OR of these flags. Returning the int matches what
    `InputCommands.dispatch_key_event` ultimately wants, and avoids
    ``ValueError: 10 is not a valid KeyModifier`` when callers combine flags.
    """
    if not spec:
        return None
    total = 0
    for raw in spec.split(','):
        token = raw.strip().upper()
        if not token:
            continue
        token = _MODIFIER_ALIASES.get(token, token)
        try:
            total |= int(KeyModifier[token])
        except KeyError as e:
            raise CliError(
                f'unknown modifier {raw!r}. Use ALT, CTRL/CONTROL, META/CMD, SHIFT.',
                exit_code=2,
            ) from e
    return total or None


@group_app.command(
    'press',
    help='Press a single key (down + brief hold + up).',
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session s keyboard press ENTER\n'
        '  pydoll-cli --session s keyboard press A --modifiers CONTROL\n'
        '  pydoll-cli --session s keyboard press F5\n'
    ),
)
@run_async
async def press(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help='Key name (e.g. ENTER, TAB, F1).')],
    modifiers: Annotated[
        str | None,
        typer.Option('--modifiers', help='Comma-separated: ALT, CONTROL, META, SHIFT.'),
    ] = None,
    interval_ms: Annotated[
        int,
        typer.Option('--interval-ms', help='How long to hold the key in ms (default 100).'),
    ] = 100,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    key_enum = _resolve_key(key)
    mods = _resolve_modifiers(modifiers)
    async with open_browser(opts) as (_browser, tab):
        await tab.keyboard.press(key_enum, modifiers=mods, interval=interval_ms / 1000.0)
    printer.emit({'pressed': key.upper(), 'modifiers': modifiers or ''})


@group_app.command(
    'hotkey',
    help='Press a key combination (2 or 3 keys).',
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session s keyboard hotkey CONTROL S\n'
        '  pydoll-cli --session s keyboard hotkey CONTROL SHIFT P\n'
    ),
)
@run_async
async def hotkey(
    ctx: typer.Context,
    keys: Annotated[
        list[str],
        typer.Argument(help='2 or 3 key names (modifier first, e.g. CONTROL S).'),
    ],
) -> None:
    if not keys or not (2 <= len(keys) <= 3):
        raise CliError('hotkey: pass 2 or 3 key names.', exit_code=2)
    resolved = [_resolve_key(k) for k in keys]
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (_browser, tab):
        if len(resolved) == 2:
            await tab.keyboard.hotkey(resolved[0], resolved[1])
        else:
            await tab.keyboard.hotkey(resolved[0], resolved[1], resolved[2])
    printer.emit({'hotkey': [k.upper() for k in keys]})


@group_app.command(
    'down',
    help='Press a key down without releasing (use `keyboard up` to release).',
)
@run_async
async def down(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help='Key name.')],
    modifiers: Annotated[
        str | None,
        typer.Option('--modifiers', help='Comma-separated modifiers.'),
    ] = None,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    key_enum = _resolve_key(key)
    mods = _resolve_modifiers(modifiers)
    async with open_browser(opts) as (_browser, tab):
        await tab.keyboard.down(key_enum, modifiers=mods)
    printer.emit({'down': key.upper()})


@group_app.command(
    'up',
    help='Release a previously held-down key.',
)
@run_async
async def up(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help='Key name.')],
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    key_enum = _resolve_key(key)
    async with open_browser(opts) as (_browser, tab):
        await tab.keyboard.up(key_enum)
    printer.emit({'up': key.upper()})


@group_app.command(
    'type',
    help='Type text via the page-level keyboard (no element targeting).',
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session s keyboard type "hello"\n'
        '  pydoll-cli --session s keyboard type "hello" --humanize\n'
    ),
)
@run_async
async def type_(
    ctx: typer.Context,
    text: Annotated[str, typer.Argument(help='Text to type.')],
    humanize: Annotated[
        bool,
        typer.Option('--humanize', help='Variable cadence + ~2% realistic typos.'),
    ] = False,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (_browser, tab):
        await tab.keyboard.type_text(text, humanize=humanize)
    printer.emit({'typed': text, 'humanize': humanize})
