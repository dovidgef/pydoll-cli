"""`mouse` subcommand group — dispatch mouse events at page coordinates.

Distinct from `click SELECTOR` (which finds an element by selector). Use
this when the target is positional (canvas, drag-and-drop, hover-only menus).
"""

from __future__ import annotations

from typing import Annotated

import typer
from pydoll.protocol.input.types import MouseButton

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer

group_app = typer.Typer(
    help='Mouse input by viewport coordinate (move, click, drag, hover).',
    no_args_is_help=True,
    rich_markup_mode='rich',
)


def _resolve_button(name: str) -> MouseButton:
    upper = name.upper()
    try:
        return MouseButton[upper]
    except KeyError as e:
        raise CliError(
            f'unknown mouse button {name!r}. Use LEFT, RIGHT, or MIDDLE.',
            exit_code=2,
        ) from e


@group_app.command(
    'move',
    help='Move the cursor to (X, Y) in CSS pixels (viewport coords).',
)
@run_async
async def move(
    ctx: typer.Context,
    x: Annotated[float, typer.Argument(help='Target X (CSS pixels).')],
    y: Annotated[float, typer.Argument(help='Target Y (CSS pixels).')],
    humanize: Annotated[
        bool,
        typer.Option('--humanize', help='Curved path with realistic timing.'),
    ] = False,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (_browser, tab):
        await tab.mouse.move(x, y, humanize=humanize)
    printer.emit({'moved': [x, y], 'humanize': humanize})


@group_app.command(
    'click',
    help='Click at (X, Y) in CSS pixels.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session s mouse click 100 200\n'
        '  pydoll-cli --session s mouse click 50 50 --button right\n'
        '  pydoll-cli --session s mouse click 100 100 --double --humanize\n'
    ),
)
@run_async
async def click(
    ctx: typer.Context,
    x: Annotated[float, typer.Argument(help='Target X (CSS pixels).')],
    y: Annotated[float, typer.Argument(help='Target Y (CSS pixels).')],
    button: Annotated[
        str,
        typer.Option('--button', help='Mouse button: LEFT, RIGHT, MIDDLE.', case_sensitive=False),
    ] = 'left',
    double: Annotated[
        bool,
        typer.Option('--double', help='Double-click instead of single.'),
    ] = False,
    humanize: Annotated[
        bool,
        typer.Option('--humanize', help='Curved approach + realistic click timing.'),
    ] = False,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    btn = _resolve_button(button)
    async with open_browser(opts) as (_browser, tab):
        if double:
            await tab.mouse.double_click(x, y, button=btn, humanize=humanize)
        else:
            await tab.mouse.click(x, y, button=btn, humanize=humanize)
    printer.emit(
        {'clicked': [x, y], 'button': button.upper(), 'double': double, 'humanize': humanize},
    )


@group_app.command(
    'drag',
    help='Drag from (X1, Y1) to (X2, Y2) holding the left button.',
)
@run_async
async def drag(
    ctx: typer.Context,
    x1: Annotated[float, typer.Argument(help='Start X.')],
    y1: Annotated[float, typer.Argument(help='Start Y.')],
    x2: Annotated[float, typer.Argument(help='End X.')],
    y2: Annotated[float, typer.Argument(help='End Y.')],
    humanize: Annotated[
        bool,
        typer.Option('--humanize', help='Curved drag path.'),
    ] = False,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (_browser, tab):
        await tab.mouse.drag(x1, y1, x2, y2, humanize=humanize)
    printer.emit({'dragged': {'from': [x1, y1], 'to': [x2, y2]}, 'humanize': humanize})


@group_app.command(
    'hover',
    help='Move the cursor to the center of an element by selector (no click).',
)
@run_async
async def hover(
    ctx: typer.Context,
    selector: Annotated[str, typer.Argument(help='CSS or XPath selector.')],
    wait: Annotated[
        int,
        typer.Option('--wait', help='Seconds to poll for the element.'),
    ] = 5,
    humanize: Annotated[
        bool,
        typer.Option('--humanize', help='Curved cursor path to the target.'),
    ] = False,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (_browser, tab):
        element = await tab.query(selector, timeout=wait, raise_exc=False)
        if element is None:
            raise CliError(f'Selector not found: {selector!r}', exit_code=4)
        # Read element's bounding box and move to its centre.
        result = await tab.execute_script(
            'const r = argument.getBoundingClientRect();'
            ' [r.left + r.width / 2, r.top + r.height / 2]',
            element,
            return_by_value=True,
        )
        coords = _scalar_value(result)
        if not (isinstance(coords, list) and len(coords) == 2):
            raise CliError('hover: failed to read element bounds.', exit_code=1)
        cx, cy = float(coords[0]), float(coords[1])
        await tab.mouse.move(cx, cy, humanize=humanize)
    printer.emit({'hover': selector, 'at': [cx, cy], 'humanize': humanize})


def _scalar_value(result: object) -> object:
    if not isinstance(result, dict):
        return None
    inner = result.get('result', {})
    if isinstance(inner, dict) and ('result' in inner or 'exceptionDetails' in inner):
        ro = inner.get('result') or {}
    else:
        ro = inner if isinstance(inner, dict) else {}
    if isinstance(ro, dict) and 'value' in ro:
        return ro['value']
    return ro
