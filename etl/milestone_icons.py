"""Milestone BI icon set: outline icons for KPI tiles, in the house palette.

Every icon is drawn on a 48-unit grid with a 2.8 stroke and round joins, as two groups: the line
work in navy, and the one part that carries the meaning in gold. Nothing else is coloured, so a
strip of five reads as one family and never competes with the green and red that mean better or
worse. Markup uses single quotes only, so the same text can sit in an SVG file, in HTML, or
inside a DAX string that builds an SVG measure.

Two ways to use it:

* A `cardVisual` KPI strip - `card_images(measures, icons)` returns the visual's `image` object:
  shared settings on the default selector, then one entry per measure (selector
  `{"metadata": queryRef}`) pointing at a registered SVG. `resources(icons)` gives the files to
  write into StaticResources/RegisteredResources and list in report.json as type Image.
* An SVG measure - splice `markup(name)` into the DAX text inside a translated, scaled <g>.

Proven in Desktop 2.157 and the Service on the P&L statement strip (2026-09-21).
"""

from __future__ import annotations

VERSION = "1.1.0"  # 1.1.0: card_images sizes the icon from the strip width

NAVY = "#111F38"
GOLD = "#C9A227"

_DOLLAR = ("<path d='M3.4 -2.6c-.6-1.2-1.8-1.9-3.4-1.9-2 0-3.4 1-3.4 2.4 0 3.3 6.8 1.5 6.8 4.9 0 1.5-1.4 2.5-3.4 2.5"
           "-1.7 0-3-.8-3.6-2'/><path d='M0 -6.4v12.8'/>")
_AXES = "<path d='M6 6v36h36'/>"
_SHIELD = "<path d='M24 5l16 6v12c0 10-7 17-16 20C15 40 8 33 8 23V11z'/>"
_CARD = "<rect x='5' y='10' width='38' height='28' rx='4'/><path d='M5 19h38'/>"
_CLIPBOARD = "<path d='M18 9h-6v34h24V9h-6'/><rect x='18' y='5' width='12' height='8' rx='2'/>"
_CALENDAR = "<rect x='6' y='9' width='36' height='33' rx='3'/><path d='M6 18h36M15 5v8M33 5v8'/>"
_RING = "<circle cx='24' cy='24' r='18'/>"
_HAND = ("<path d='M4 31h6v12H4z'/><path d='M10 33h8c2.2 0 3.6 1.6 6 1.6h5.5a2.4 2.4 0 0 1 0 4.8H22'/>"
         "<path d='M10 41l11.5 2.6c1.6.4 3.2.2 4.7-.5L43 35.6a2.3 2.3 0 0 0-2.1-4.1L32.5 35.3'/>")


def _dollar(x: float, y: float, scale: float) -> str:
    return f"<g transform='translate({x} {y}) scale({scale})'>{_DOLLAR}</g>"


def _person(x: float, y: float, r: float = 6.5, w: float = 22, h: float = 13, b: float = 40) -> str:
    return f"<circle cx='{x}' cy='{y}' r='{r}'/><path d='M{x - w / 2} {b}c0-{h} {w}-{h} {w} 0'/>"


# name: (navy line work, gold accent)
ICONS: dict[str, tuple[str, str]] = {
    # ---- money ---------------------------------------------------------------------------
    "coin": (_RING, _dollar(24, 24, 1.7)),
    "euro": (_RING, "<path d='M31 15.5a10 10 0 1 0 0 17M13 21.5h13M13 26.5h13'/>"),
    "bag": ("<path d='M17 6h14l-3.5 6.5h-7z'/><path d='M20.5 12.5C13.5 17 9 24 9 31.5 9 38.5 14 43 24 43s15-4.5 15-11.5"
            "c0-7.5-4.5-14.5-11.5-19'/>", _dollar(24, 29.5, 1.05)),
    "hand-coin": (_HAND, "<circle cx='24' cy='14' r='9.5'/><circle cx='24' cy='14' r='3'/>"),
    "person-coin": (_person(17, 14, 6.5, 24, 14, 40), "<circle cx='36' cy='31' r='8'/><path d='M36 27.5v7'/>"),
    "receipt": ("<path d='M10 5h28v38l-4.7-3-4.7 3-4.6-3-4.6 3-4.7-3L10 43z'/>", "<path d='M17 15h14M17 22h14M17 29h8'/>"),
    "tag": ("<path d='M6 6h17l19 19-17 17L6 23z'/>", "<circle cx='16' cy='16' r='3.2'/>"),
    "layers": ("<path d='M24 5l19 10-19 10L5 15z'/><path d='M5 24l19 10 19-10'/>", "<path d='M5 33l19 10 19-10'/>"),
    # ---- trade ---------------------------------------------------------------------------
    "cart": ("<path d='M4 8h7l5 23h21l5-16H13'/>", "<circle cx='19' cy='39' r='2.8'/><circle cx='34' cy='39' r='2.8'/>"),
    "truck": ("<path d='M4 11h23v23H4zM27 19h9l8 9v6H27'/>", "<circle cx='13' cy='36' r='4' fill='#FFFFFF'/>"
              "<circle cx='34' cy='36' r='4' fill='#FFFFFF'/>"),
    "card": (_CARD, "<path d='M11 30h10'/>"),
    "card-check": (_CARD, "<path d='M25 29l4.5 4.5 8-9'/>"),
    "chip": ("<rect x='10' y='10' width='28' height='28' rx='3'/><path d='M4 18h6M4 30h6M38 18h6M38 30h6M18 4v6M30 4v6"
             "M18 38v6M30 38v6'/>", "<rect x='18' y='18' width='12' height='12' rx='1.5'/>"),
    "globe": (_RING + "<path d='M6 24h36'/>", "<path d='M24 6c-9 8-9 28 0 36 9-8 9-28 0-36'/>"),
    "laptop": ("<path d='M9 10h30v22H9zM4 39h40'/>", "<path d='M17 18h14M17 24h8'/>"),
    "sliders": ("<path d='M6 12h36M6 24h36M6 36h36'/>", "<circle cx='16' cy='12' r='3.6' fill='#FFFFFF'/>"
                "<circle cx='32' cy='24' r='3.6' fill='#FFFFFF'/><circle cx='21' cy='36' r='3.6' fill='#FFFFFF'/>"),
    # ---- people --------------------------------------------------------------------------
    "people": (_person(24, 15), _person(9, 20, 4.5, 14, 9, 38) + _person(39, 20, 4.5, 14, 9, 38)),
    "person-plus": (_person(19, 15, 7, 26, 15, 41), "<path d='M38 8v14M31 15h14'/>"),
    "exit": ("<path d='M26 6H8v36h18'/><circle cx='20' cy='24' r='1.6'/>", "<path d='M22 24h20M35 17l7 7-7 7'/>"),
    "heart-pulse": ("<path d='M24 41S6 30 6 18a9.5 9.5 0 0 1 18-4 9.5 9.5 0 0 1 18 4c0 12-18 23-18 23z'/>",
                    "<path d='M13 24h6l3-6 5 11 3-5h5'/>"),
    "smile": (_RING + "<path d='M17 18v3M31 18v3'/>", "<path d='M15 28a10 10 0 0 0 18 0'/>"),
    "star-check": ("<path d='M24 5l5.9 12 13.1 1.9-9.5 9.3 2.2 13.1L24 35.1l-11.7 6.2 2.2-13.1L5 18.9 18.1 17z'/>",
                   "<path d='M18 25l4.5 4.5 8-9'/>"),
    "cap": ("<path d='M3 18l21-10 21 10-21 10z'/><path d='M12 23v10c0 3 5.5 6 12 6s12-3 12-6V23'/>", "<path d='M45 18v13'/>"),
    # ---- time ----------------------------------------------------------------------------
    "clock": (_RING, "<path d='M24 13v11l7 5'/>"),
    "clock-alert": ("<circle cx='21' cy='27' r='16'/><path d='M21 18v9l5 4'/>", "<path d='M42 5v11M42 21.5v.5'/>"),
    "stopwatch": ("<circle cx='24' cy='27' r='15'/><path d='M19 5h10M24 5v7'/>", "<path d='M24 19v8l5 3'/>"),
    "hourglass": ("<path d='M11 5h26M11 43h26M14 5c0 10 10 12 10 19s-10 9-10 19M34 5c0 10-10 12-10 19s10 9 10 19'/>",
                  "<path d='M19 38h10M21 13h6'/>"),
    "calendar": (_CALENDAR, "<path d='M14 27h4M22 27h4M30 27h4M14 34h4M22 34h4'/>"),
    "calendar-check": (_CALENDAR, "<path d='M16 30l5 5 10-10'/>"),
    "repeat": ("<path d='M8 22a16 16 0 0 1 28-9M37 4v9h-9'/>", "<path d='M40 26a16 16 0 0 1-28 9M11 44v-9h9'/>"),
    # ---- measures and ratios -------------------------------------------------------------
    "percent": (_RING + "<path d='M18 30L30 18'/><circle cx='18.5' cy='18.5' r='2.6'/><circle cx='29.5' cy='29.5' r='2.6'/>",
                "<path d='M24 6a18 18 0 0 1 18 18' stroke-width='4.4'/>"),
    "gauge": ("<path d='M5 35a19 19 0 0 1 38 0z'/>", "<path d='M24 35l9-14'/><circle cx='24' cy='35' r='1.6'/>"),
    "scales": ("<path d='M24 7v35M15 42h18M9 12h30'/>", "<path d='M9 12L4 25a5.5 5.5 0 0 0 10 0zM39 12l-5 13a5.5 5.5 0 0 0 10 0z'/>"),
    "bars": ("<path d='M5 42h38'/><rect x='9' y='26' width='8' height='16'/><rect x='31' y='19' width='8' height='23'/>",
             "<rect x='20' y='9' width='8' height='33'/>"),
    "bars-line": ("<path d='M5 42h38'/><rect x='9' y='28' width='8' height='14'/><rect x='20' y='12' width='8' height='30'/>"
                  "<rect x='31' y='22' width='8' height='20'/>", "<path d='M4 20h40' stroke-dasharray='5 5'/>"),
    "trend-up": (_AXES, "<path d='M12 34l10-11 6 5 12-14M31 14h9v9'/>"),
    "trend-down": (_AXES, "<path d='M12 14l10 11 6-5 12 14M40 25v9h-9'/>"),
    "target": ("<circle cx='21' cy='27' r='17'/><circle cx='21' cy='27' r='10'/><path d='M21 27L40 8M35 5.5v7.5h7.5'/>",
               "<circle cx='21' cy='27' r='3.2' fill='#C9A227'/>"),
    "floor": ("<path d='M5 41h38M5 41l5 4M15 41l5 4M25 41l5 4M35 41l5 4'/>", "<path d='M24 6v24M15 22l9 9 9-9'/>"),
    "umbrella": ("<path d='M4 25a20 20 0 0 1 40 0z'/>", "<path d='M24 25v13a4.5 4.5 0 0 0 9 0M24 5V3'/>"),
    # ---- risk and records ----------------------------------------------------------------
    "cancel": (_RING, "<path d='M11.5 11.5l25 25'/>"),
    "warning": ("<path d='M24 6L45 42H3z'/>", "<path d='M24 19v11M24 35.5v.5'/>"),
    "alert-circle": (_RING, "<path d='M24 13v13M24 33.5v.5'/>"),
    "shield-check": (_SHIELD, "<path d='M17 24l5 5 9-10'/>"),
    "shield-alert": (_SHIELD, "<path d='M24 15v11M24 32.5v.5'/>"),
    "bank": ("<path d='M4 18L24 6l20 12zM5 42h38'/>", "<path d='M11 24v12M24 24v12M37 24v12'/>"),
    "clipboard-check": (_CLIPBOARD, "<path d='M17 28l5 5 9-10'/>"),
    "clipboard-x": (_CLIPBOARD, "<path d='M18 23l12 12M30 23L18 35'/>"),
    "database": ("<ellipse cx='24' cy='11' rx='15' ry='5.5'/><path d='M9 11v26c0 3 6.7 5.5 15 5.5s15-2.5 15-5.5V11'/>",
                 "<path d='M9 24c0 3 6.7 5.5 15 5.5s15-2.5 15-5.5'/>"),
}


def markup(name: str, stroke: str = NAVY, accent: str = GOLD) -> str:
    """The icon's two groups, ready to sit inside any <svg> or a translated, scaled <g>."""
    lines, mark = ICONS[name]
    return (f"<g fill='none' stroke-width='2.8' stroke-linecap='round' stroke-linejoin='round'>"
            f"<g stroke='{stroke}'>{lines}</g><g stroke='{accent}'>{mark}</g></g>")


def svg_file(name: str, stroke: str = NAVY, accent: str = GOLD) -> str:
    return f"<svg viewBox='0 0 48 48' xmlns='http://www.w3.org/2000/svg'>{markup(name, stroke, accent)}</svg>\n"


def resource_name(icon: str) -> str:
    """The registered-resource file name for an icon: 'shield-check' -> 'IconShieldCheck.svg'."""
    return "Icon" + "".join(part.capitalize() for part in icon.split("-")) + ".svg"


def resources(icons) -> dict[str, str]:
    """Registered name -> SVG text for every icon named, deduplicated, in a stable order."""
    return {resource_name(i): svg_file(i) for i in sorted(set(icons))}


def _lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def card_images(measures: list[dict], icons: list[str], strip_width: int, icon_px: int = 36) -> list[dict]:
    """The `image` object for a multi-value cardVisual: one icon to the left of each value.
    `measures` are the card's projections (each with a queryRef), `icons` the icon per measure,
    `strip_width` the visual's width in canvas pixels.

    `imageAreaSize` is a PERCENTAGE of one tile's width, not pixels: 34 drew a 95px icon across a
    278px tile and pushed the value out of the card. It is worked out here so the icon comes to
    about `icon_px` whatever the strip's width and tile count. `size` made no visible difference
    at 12, 30 or 100 with fixedSize on; with fixedSize off the icon filled the tile."""
    if len(measures) != len(icons):
        raise ValueError(f"{len(measures)} measures but {len(icons)} icons")
    area = max(8, round(icon_px / (strip_width / len(measures)) * 100))
    shared = {"properties": {
        "show": _lit("true"), "position": _lit("'Left'"), "fit": _lit("'Fit'"), "fixedSize": _lit("true"),
        "size": _lit("30L"), "imageAreaSize": _lit(f"{area}L"), "padding": _lit("6L")},
        "selector": {"id": "default"}}
    each = [{"properties": {"imageType": _lit("'image'"), "image": {"image": {
        "name": _lit(f"'{resource_name(icon)}'"),
        "url": {"expr": {"ResourcePackageItem": {"PackageName": "RegisteredResources", "PackageType": 1,
                                                 "ItemName": resource_name(icon)}}},
        "scaling": _lit("'Fit'")}}},
        "selector": {"metadata": m["queryRef"]}} for m, icon in zip(measures, icons)]
    return [shared] + each
