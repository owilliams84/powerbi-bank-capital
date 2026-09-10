"""Generate the PBIR report definition - five pages, the Milestone theme and every visual.

PBIR stores one JSON file per visual and wraps every property in the same
{"expr": {"Literal": {"Value": ...}}} envelope. Hand-editing that is how typos get in, so the
report is generated from this file: the helpers own the envelope and the page functions read as
layout.

    python etl/build_report.py

Rewrites <report>/definition/pages from scratch every run. That matters - a renamed visual left
behind on disk still renders, as an empty box.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "Bank Capital"
REPORT = ROOT / f"{NAME}.Report"
PAGES = REPORT / "definition" / "pages"
RESOURCES = REPORT / "StaticResources" / "RegisteredResources"
ASSETS = ROOT / "etl" / "assets"

CANVAS_W, CANVAS_H = 1440, 900

# --------------------------------------------------------------------------------------------
# Palette: milestonebi.com's own tokens.
# --------------------------------------------------------------------------------------------
PAPER = "#F4F6FA"
CARD = "#FFFFFF"
RULE = "#E3E7EF"
INK = "#0A0917"
BODY = "#4A5768"
MUTED = "#667284"
GOLD = "#C9A227"
GOLD_TEXT = "#8A6D14"
NAVY = "#111F38"
SLATE = "#7C8598"
LIGHT = "#BCC1D2"
GOOD = "#1E7A4C"
BAD = "#B3261E"

THEME_NAME = "MilestoneTheme.json"
MARK_NAME = "MilestoneMark.svg"

# --------------------------------------------------------------------------------------------
# Expression envelope helpers
# --------------------------------------------------------------------------------------------


def lit(value) -> dict:
    """Wrap a literal in the expression envelope PBIR expects.

    The suffix is load-bearing: 'D' for a double, 'L' for an integer, quotes for text. Getting
    it wrong makes Desktop drop the property silently rather than complain.
    """
    if isinstance(value, bool):
        v = "true" if value else "false"
    elif isinstance(value, int):
        v = f"{value}L"
    elif isinstance(value, float):
        v = f"{value}D"
    else:
        v = f"'{value}'"
    return {"expr": {"Literal": {"Value": v}}}


def colour(hex_code: str) -> dict:
    return {"solid": {"color": lit(hex_code)}}


def obj(**props) -> list:
    return [{"properties": props}]


def obj_for(metadata: str, **props) -> dict:
    return {"properties": props, "selector": {"metadata": metadata}}


def obj_for_value(table: str, col: str, value, **props) -> dict:
    """A property block scoped to one category value."""
    return {"properties": props, "selector": {"data": [{"scopeId": {"Comparison": {
        "ComparisonKind": 0,
        "Left": {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": col}},
        "Right": lit(value)["expr"],
    }}}]}}


def measure(table: str, name: str, display: str | None = None) -> dict:
    field = {
        "field": {"Measure": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}},
        "queryRef": f"{table}.{name}",
        "nativeQueryRef": name,
    }
    if display:
        field["displayName"] = display
    return field


def column(table: str, name: str, display: str | None = None, active: bool = True) -> dict:
    field = {
        "field": {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}},
        "queryRef": f"{table}.{name}",
        "nativeQueryRef": name,
    }
    if active:
        field["active"] = True
    if display:
        field["displayName"] = display
    return field


def m(name: str, display: str | None = None) -> dict:
    return measure("Metrics", name, display)


def sort_by(field: dict, direction: str = "Descending") -> dict:
    return {"sort": [{"field": field["field"], "direction": direction}], "isDefaultSort": True}


def categorical_filter(name: str, table: str, col: str, values: list, alias: str = "t") -> dict:
    """A visual-level 'this column is one of these values' filter."""
    return {
        "name": name,
        "field": {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": col}},
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": alias, "Entity": table, "Type": 0}],
            "Where": [{"Condition": {"In": {
                "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": alias}},
                                            "Property": col}}],
                "Values": [[lit(v)["expr"]] for v in values],
            }}}],
        },
    }


PANEL_FILTER = lambda name: categorical_filter(name, "Bank", "In Constant Panel", ["Yes"], "b")


# --------------------------------------------------------------------------------------------
# Container chrome
# --------------------------------------------------------------------------------------------


def chrome(title: str | None = None, subtitle: str | None = None, *,
           transparent: bool = False) -> dict:
    """Card background, hairline border and the small bold title every panel shares.

    subtitle is the second positional parameter and transparent is keyword-only: with them the
    other way round, chrome("Title", "Subtitle") put the caption into transparent and dropped it.
    """
    show = not transparent
    out = {
        "padding": obj(top=lit(8.0), bottom=lit(8.0), left=lit(10.0), right=lit(10.0)),
        "dropShadow": obj(show=lit(False)),
        "background": obj(show=lit(show), color=colour(CARD), transparency=lit(0.0)),
        "border": obj(show=lit(show), color=colour(RULE), radius=lit(4)),
    }
    if title:
        out["title"] = obj(show=lit(True), text=lit(title), fontSize=lit(10.5), bold=lit(True),
                           fontColor=colour(INK), heading=lit("Heading3"))
        if subtitle:
            out["subTitle"] = obj(show=lit(True), text=lit(subtitle), fontSize=lit(8.5),
                                  fontColor=colour(MUTED))
    else:
        out["title"] = obj(show=lit(False))
    return out


def visual(name: str, vtype: str, x: int, y: int, w: int, h: int, z: int,
           query: dict | None = None, objects: dict | None = None,
           container: dict | None = None, filters: list | None = None) -> dict:
    node: dict = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.5.0/schema.json",
        "name": name,
        "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z},
        "visual": {"visualType": vtype},
    }
    if query is not None:
        node["visual"]["query"] = query
    if objects:
        node["visual"]["objects"] = objects
    node["visual"]["visualContainerObjects"] = container or chrome()
    if filters:
        # filterConfig is a sibling of "visual" at the root, not a child of it.
        node["filterConfig"] = {"filters": filters}
    return node


# --------------------------------------------------------------------------------------------
# Reusable formatting blocks
# --------------------------------------------------------------------------------------------


def axis(show_title: bool = False, gridlines: bool = False, size: float = 8.5, **extra) -> list:
    return [{"properties": {
        "show": lit(True), "showAxisTitle": lit(show_title), "fontSize": lit(size),
        "labelColor": colour(MUTED), "gridlineShow": lit(gridlines),
        **({"gridlineColor": colour(RULE)} if gridlines else {}),
        **extra,
    }}]


def legend(show: bool = True, position: str = "Top") -> list:
    return [{"properties": {
        "show": lit(show), "position": lit(position), "showTitle": lit(False),
        "fontSize": lit(8.5), "labelColor": colour(MUTED),
    }}]


def no_labels() -> list:
    return [{"properties": {"show": lit(False)}}]


def data_labels(size: float = 8.5, units: str = "1", colour_hex: str = BODY) -> list:
    return [{"properties": {
        "show": lit(True), "fontSize": lit(size), "color": colour(colour_hex),
        "labelDisplayUnits": lit(units),
    }}]


def series_colour(mapping: dict[str, str]) -> list:
    return [obj_for(k, fill=colour(v)) for k, v in mapping.items()]


def value_colours(table: str, col: str, mapping: dict) -> list:
    return [obj_for_value(table, col, k, fill=colour(v)) for k, v in mapping.items()]


def line_style() -> list:
    return [{"properties": {
        "strokeWidth": lit(2), "lineStyle": lit("solid"), "showMarker": lit(True),
    }}]


def no_chrome() -> dict:
    return {
        "padding": obj(top=lit(0.0), bottom=lit(0.0), left=lit(0.0), right=lit(0.0)),
        "dropShadow": obj(show=lit(False)),
        "background": obj(show=lit(False)),
        "border": obj(show=lit(False)),
        "title": obj(show=lit(False)),
    }


def textbox(name: str, x: int, y: int, w: int, h: int, z: int, paragraphs: list,
            background: str | None = None) -> dict:
    """paragraphs: each is a list of runs, or a single run dict for a one-run paragraph."""
    out = []
    for para in paragraphs:
        runs = para if isinstance(para, list) else [para]
        text_runs = []
        for run in runs:
            style = {"fontSize": f"{run.get('size', 11)}pt", "color": run.get("color", BODY)}
            if run.get("bold"):
                style["fontWeight"] = "bold"
            if run.get("family"):
                style["fontFamily"] = run["family"]
            if run.get("spacing"):
                style["letterSpacing"] = run["spacing"]
            text_runs.append({"value": run["text"], "textStyle": style})
        node = {"textRuns": text_runs}
        if runs[0].get("align"):
            node["horizontalTextAlignment"] = runs[0]["align"]
        out.append(node)
    container = no_chrome()
    if background:
        container["background"] = obj(show=lit(True), color=colour(background),
                                      transparency=lit(0.0))
        container["padding"] = obj(top=lit(4.0), bottom=lit(4.0), left=lit(10.0),
                                   right=lit(10.0))
    node = visual(name, "textbox", x, y, w, h, z, container=container)
    node["visual"]["objects"] = {"general": [{"properties": {"paragraphs": out}}]}
    return node


def note(name: str, x: int, y: int, w: int, h: int, z: int, heading: str,
         lines: list[str]) -> dict:
    """A card of prose - used where the honest caveat needs more room than a subtitle."""
    paras: list = [[{"text": heading, "size": 10.5, "color": INK, "bold": True}]]
    for line in lines:
        paras.append([{"text": "", "size": 4, "color": BODY}])
        paras.append([{"text": line, "size": 9, "color": BODY}])
    node = textbox(name, x, y, w, h, z, paras)
    node["visual"]["visualContainerObjects"] = chrome()
    return node


def image(name: str, x: int, y: int, w: int, h: int, z: int, resource: str) -> dict:
    node = visual(name, "image", x, y, w, h, z, container=no_chrome())
    node["visual"]["objects"] = {
        "general": [{"properties": {"imageUrl": {"expr": {"ResourcePackageItem": {
            "PackageName": "RegisteredResources", "PackageType": 1, "ItemName": resource}}}}}],
        "imageScaling": [{"properties": {"imageScalingType": lit("Fit")}}],
    }
    return node


def kpi_card(name: str, x: int, y: int, w: int, h: int, z: int, measures: list[dict],
             filters: list | None = None, value_size: float = 17.0) -> dict:
    return visual(
        name, "cardVisual", x, y, w, h, z,
        query={"queryState": {"Data": {"projections": measures}}},
        objects={
            "general": [{"properties": {}}],
            "value": [{"properties": {
                "fontSize": lit(value_size), "bold": lit(True), "fontColor": colour(INK),
                "fontFamily": lit("Segoe UI"), "horizontalAlignment": lit("Left"),
                # The measures carry their own scaling in the format string (EUR bn).
                "labelDisplayUnits": lit("1"),
            }, "selector": {"id": "default"}}],
            "label": [{"properties": {
                "show": lit(True), "fontSize": lit(8.5), "fontColor": colour(MUTED),
                "bold": lit(False), "position": lit("belowValue"),
                "horizontalAlignment": lit("Left"),
            }, "selector": {"id": "default"}}],
            "accentBar": [{"properties": {
                "show": lit(True), "color": colour(GOLD), "width": lit(3),
            }, "selector": {"id": "default"}}],
        },
        filters=filters,
    )


def slicer(name: str, x: int, y: int, w: int, h: int, z: int, table: str, col: str,
           header: str, mode: str = "Dropdown") -> dict:
    return visual(
        name, "slicer", x, y, w, h, z,
        query={"queryState": {"Values": {"projections": [column(table, col)]}}},
        objects={
            "general": [{"properties": {"orientation": lit(0)}}],
            "data": [{"properties": {"mode": lit(mode)}}],
            "header": [{"properties": {
                "show": lit(True), "text": lit(header), "textSize": lit(8.5),
                "fontColor": colour(MUTED), "bold": lit(True),
            }}],
            "items": [{"properties": {
                "fontColor": colour(BODY), "textSize": lit(9.5), "background": colour(CARD),
            }}],
        },
    )


def table_visual(name: str, x: int, y: int, w: int, h: int, z: int, fields: list[dict],
                 sort: dict | None, title: str, subtitle: str | None = None,
                 filters: list | None = None, totals: bool = False) -> dict:
    """A flat ranked table. Built as a matrix with one row field: on Desktop 2.157 a tableEx
    generated this way rendered the column fields and silently dropped every measure."""
    rows = [f for f in fields if "Column" in f["field"]]
    values = [f for f in fields if "Measure" in f["field"]]
    query: dict = {"queryState": {"Rows": {"projections": rows},
                                  "Values": {"projections": values}}}
    if sort:
        query["sortDefinition"] = sort
    return visual(
        name, "pivotTable", x, y, w, h, z,
        query=query,
        objects={
            "grid": [{"properties": {
                "gridVertical": lit(False), "gridHorizontal": lit(True),
                "gridHorizontalColor": colour(RULE), "rowPadding": lit(3),
            }}],
            "columnHeaders": [{"properties": {
                "fontSize": lit(9.0), "bold": lit(True), "fontColor": colour(INK),
                "backColor": colour(CARD), "alignment": lit("Right"),
            }}],
            "rowHeaders": [{"properties": {
                "fontSize": lit(9.0), "fontColor": colour(BODY), "backColor": colour(CARD),
            }}],
            "values": [{"properties": {
                "fontSize": lit(9.0), "fontColorPrimary": colour(BODY),
                "backColorPrimary": colour(CARD), "backColorSecondary": colour(CARD),
            }}],
            "subTotals": [{"properties": {"rowSubtotals": lit(totals),
                                          "columnSubtotals": lit(False)}}],
        },
        container=chrome(title, subtitle=subtitle),
        filters=filters,
    )


def chart(name: str, vtype: str, x: int, y: int, w: int, h: int, z: int, category: dict,
          values: list[dict], title: str, subtitle: str | None = None, *,
          series: dict | None = None, tooltips: list[dict] | None = None,
          sort: dict | None = None, colours: list | None = None, labels: list | None = None,
          show_legend: bool = False, filters: list | None = None) -> dict:
    state: dict = {"Category": {"projections": [category]}, "Y": {"projections": values}}
    if series:
        state["Series"] = {"projections": [series]}
    if tooltips:
        state["Tooltips"] = {"projections": tooltips}
    objects: dict = {
        "categoryAxis": axis(), "valueAxis": axis(gridlines=True),
        "legend": legend(show_legend), "labels": labels or no_labels(),
    }
    if vtype == "lineChart":
        objects["lineStyles"] = line_style()
    if colours:
        objects["dataPoint"] = colours
    query: dict = {"queryState": state}
    if sort:
        query["sortDefinition"] = sort
    return visual(name, vtype, x, y, w, h, z, query=query, objects=objects,
                  container=chrome(title, subtitle), filters=filters)


# --------------------------------------------------------------------------------------------
# Masthead
# --------------------------------------------------------------------------------------------


def masthead(slug: str, title: str, standfirst: str, ref: str) -> list[dict]:
    return [
        textbox(f"vBand{slug}", 0, 0, CANVAS_W, 60, 50, [
            [{"text": "", "size": 6, "color": INK}],
        ], background=INK),
        image(f"vMark{slug}", 24, 12, 44, 38, 60, MARK_NAME),
        textbox(f"vWordmark{slug}", 76, 15, 260, 32, 70, [
            [{"text": "Milestone ", "size": 15, "color": CARD, "bold": True},
             {"text": "BI", "size": 15, "color": GOLD, "bold": True}],
        ]),
        textbox(f"vRef{slug}", 1016, 22, 400, 22, 80, [
            [{"text": ref, "size": 8, "color": GOLD, "bold": True, "family": "Consolas",
              "spacing": "2px", "align": "right"}],
        ]),
        textbox(f"vTitle{slug}", 24, 74, 1000, 40, 90, [
            [{"text": title, "size": 22, "color": INK, "bold": True}],
        ]),
        textbox(f"vStand{slug}", 24, 114, 1030, 46, 95, [
            [{"text": standfirst, "size": 10, "color": BODY}],
        ]),
    ]


def page(name: str, display: str) -> dict:
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json",
        "name": name,
        "displayName": display,
        "displayOption": "FitToPage",
        "height": CANVAS_H,
        "width": CANVAS_W,
        "objects": {
            "background": obj(color=colour(PAPER), transparency=lit(0.0)),
            "displayArea": obj(verticalAlignment=lit("Top")),
        },
    }


RWA_COLOURS = {
    "Credit risk": NAVY, "Counterparty credit risk": "#3D5A80", "CVA": "#98A6BD",
    "Settlement": "#D9DEE8", "Securitisation": SLATE, "Market risk": LIGHT,
    "Large exposures": "#E8D9A8", "Operational risk": GOLD, "Other": MUTED,
    "Output floor": BAD,
}

SL_Y, SL_H = 74, 84
SL1_X, SL2_X, SL_W = 1076, 1246, 170


def quarter_controls(slug: str) -> list[dict]:
    return [
        slicer(f"vQuarter{slug}", SL1_X, SL_Y, SL_W, SL_H, 400, "Period", "Quarter", "QUARTER"),
        kpi_card(f"vAsAt{slug}", SL2_X, SL_Y, SL_W, SL_H, 410,
                 [m("As At", "Stocks read at")], value_size=11.0),
    ]


QUARTER_AXIS = column("Period", "Quarter")
QUARTER_SORT = sort_by(column("Period", "Quarter"), "Ascending")


# --------------------------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------------------------


def page_capital() -> tuple[dict, list[dict]]:
    v: list[dict] = []
    v += masthead(
        "Cap",
        "EU bank capital, September 2022 to June 2025",
        "129 banks from three EBA transparency exercises, drawn from the COREP and FINREP "
        "returns they file with their supervisors. Every ratio is recomputed from capital and "
        "risk exposure, summed first and divided once. Stocks are read at the quarter selected.",
        "01 / CAPITAL",
    )
    v += quarter_controls("Cap")

    v.append(kpi_card("vKpiCap", 24, 176, 1392, 92, 500, [
        m("CET1 Ratio", "CET1 ratio, sector"),
        m("CET1 Ratio, Average of Banks", "CET1, average of banks"),
        m("CET1 Ratio, Median of Banks", "CET1, median bank"),
        m("Total Capital Ratio", "Total capital ratio"),
        m("Leverage Ratio", "Leverage ratio"),
        m("CET1 Capital", "CET1 capital"),
    ]))

    v.append(chart(
        "vTrend", "lineChart", 24, 284, 900, 300, 600,
        QUARTER_AXIS,
        [m("CET1 Ratio (Constant Panel)", "Sector ratio"),
         m("CET1 Ratio, Average of Banks (Constant Panel)", "Average of banks")],
        "CET1 ratio by quarter, the 101 banks present throughout",
        "Two honest-looking numbers from the same data. The gap between them is the size of "
        "the bank, and it never closes",
        sort=QUARTER_SORT,
        colours=series_colour({
            "Metrics.CET1 Ratio (Constant Panel)": NAVY,
            "Metrics.CET1 Ratio, Average of Banks (Constant Panel)": GOLD}),
        show_legend=True,
    ))

    v.append(chart(
        "vSize", "clusteredBarChart", 940, 284, 476, 300, 610,
        column("Bank", "Size Band"),
        [m("CET1 Ratio", "Sector ratio"), m("CET1 Ratio, Average of Banks", "Average of banks")],
        "CET1 ratio by bank size",
        "The largest banks run the thinnest ratios, and they hold most of the risk",
        tooltips=[m("Banks Reporting", "Banks"), m("Total Risk Exposure", "RWAs")],
        sort=sort_by(column("Bank", "Size Band"), "Ascending"),
        colours=series_colour({"Metrics.CET1 Ratio": NAVY,
                               "Metrics.CET1 Ratio, Average of Banks": GOLD}),
        show_legend=True, labels=data_labels(),
    ))

    v.append(table_visual(
        "vCountries", 24, 600, 880, 276, 620,
        [
            column("Bank", "Country"),
            m("Banks Reporting", "Banks"),
            m("CET1 Ratio", "CET1, sector"),
            m("CET1 Ratio, Average of Banks", "CET1, average"),
            m("Total Capital Ratio", "Total capital"),
            m("Leverage Ratio", "Leverage"),
            m("Total Risk Exposure", "RWAs"),
        ],
        sort_by(m("Total Risk Exposure")),
        "By country",
        "Sorted by risk exposure. A country with one or two banks is a bank, not a banking system",
    ))

    v.append(note(
        "vAvgNote", 920, 600, 496, 276, 630,
        "The average bank is not the sector",
        ["Average the 119 reported CET1 ratios at June 2025 and you get 22.7%. Add up the "
         "capital and the risk-weighted assets and divide once and you get 16.2%. The median "
         "bank sits at 18.0%.",
         "All three are correct answers to different questions. The average weights a "
         "€10bn lender the same as a €2.5tn one, and the small banks carry the most capital "
         "per euro of risk - so it describes no bank and no system.",
         "The Key Metrics template that published the ratio directly was withdrawn in 2025. "
         "Recomputing from components matches it to six decimal places where both exist."],
    ))

    return page("pgCapital", "Capital"), v


def page_risk() -> tuple[dict, list[dict]]:
    v: list[dict] = []
    v += masthead(
        "Rwa",
        "What the capital is held against",
        "Risk-weighted assets by risk type, from the OV1 template. The ten top-level lines "
        "reconcile to the reported total for every bank in every quarter. 2025 brings the "
        "CRR3 output floor, and with it a pre-floor ratio to compare against.",
        "02 / RISK WEIGHTS",
    )
    v += quarter_controls("Rwa")

    v.append(kpi_card("vKpiRwa", 24, 176, 1392, 92, 500, [
        m("Total Risk Exposure", "Risk-weighted assets"),
        m("Total Assets", "Total assets"),
        m("RWA Density", "RWA density"),
        m("CET1 Ratio Pre-Floor", "CET1, before the floor"),
        m("Output Floor Cost", "Cost of the floor"),
    ]))

    v.append(chart(
        "vMix", "hundredPercentStackedColumnChart", 24, 284, 900, 300, 600,
        QUARTER_AXIS, [m("RWA by Component", "RWAs")],
        "Risk-weighted assets by risk type, constant panel",
        "Credit risk is the book; operational risk is the second-largest charge on it",
        series=column("Item", "RWA Component", active=False),
        sort=QUARTER_SORT,
        colours=value_colours("Item", "RWA Component", RWA_COLOURS), show_legend=True,
        filters=[PANEL_FILTER("fPanelMix")],
    ))

    v.append(chart(
        "vDensity", "barChart", 940, 284, 476, 300, 610,
        column("Bank", "Size Band"), [m("RWA Density")],
        "RWA density by bank size",
        "Risk weight per euro of balance sheet. Internal models are what make the big banks light",
        tooltips=[m("Total Risk Exposure", "RWAs"), m("Total Assets", "Assets")],
        sort=sort_by(column("Bank", "Size Band"), "Ascending"),
        colours=series_colour({"Metrics.RWA Density": NAVY}), labels=data_labels(),
    ))

    v.append(table_visual(
        "vLargest", 24, 600, 880, 276, 620,
        [
            column("Bank", "Bank"),
            m("Total Assets", "Assets"),
            m("Total Risk Exposure", "RWAs"),
            m("RWA Density", "Density"),
            m("CET1 Ratio", "CET1"),
            m("Leverage Ratio", "Leverage"),
        ],
        sort_by(m("Total Assets")),
        "Banks by size",
        "The largest balance sheets, and how much risk weight each one carries",
    ))

    v.append(note(
        "vFloorNote", 920, 600, 496, 276, 630,
        "The output floor, in its first year",
        ["CRR3 puts a floor under internally modelled risk weights: from 2025 a bank's RWAs "
         "cannot fall below 50% of the standardised figure, rising to 72.5% by 2030.",
         "The 2025 exercise publishes RWAs before and after the floor. At the 50% starting "
         "level it binds on one bank, and the sector-wide cost is a rounding error.",
         "The floor is phased so that it bites later. Density is the column to watch: the "
         "banks with the lightest risk weights are where it will land."],
    ))

    return page("pgRisk", "Risk weights"), v


def page_quality() -> tuple[dict, list[dict]]:
    v: list[dict] = []
    v += masthead(
        "Aq",
        "Loan quality under IFRS 9",
        "Loans and advances at amortised cost, by impairment stage. Stage 2 is a significant "
        "rise in credit risk since the loan was made; stage 3 is credit-impaired. Stage 2 "
        "moves first, which is why it is on the page.",
        "03 / ASSET QUALITY",
    )
    v += quarter_controls("Aq")

    v.append(kpi_card("vKpiAq", 24, 176, 1392, 92, 500, [
        m("Gross Loans", "Gross loans"),
        m("Stage 2 Ratio", "Stage 2"),
        m("Stage 3 Ratio", "Stage 3"),
        m("Stage 3 Coverage", "Stage 3 coverage"),
        m("Banks Reporting", "Banks"),
    ]))

    v.append(chart(
        "vStages", "lineChart", 24, 284, 900, 300, 600,
        QUARTER_AXIS, [m("Stage 2 Ratio", "Stage 2"), m("Stage 3 Ratio", "Stage 3")],
        "Stage 2 and stage 3 as a share of gross loans, constant panel",
        sort=QUARTER_SORT,
        colours=series_colour({"Metrics.Stage 2 Ratio": GOLD, "Metrics.Stage 3 Ratio": NAVY}),
        show_legend=True, filters=[PANEL_FILTER("fPanelStages")],
    ))

    v.append(chart(
        "vCountryS3", "barChart", 940, 284, 476, 300, 610,
        column("Bank", "Country"), [m("Stage 3 Ratio", "Stage 3")],
        "Stage 3 ratio by country",
        tooltips=[m("Stage 3 Coverage", "Coverage"), m("Banks Reporting", "Banks")],
        sort=sort_by(m("Stage 3 Ratio")),
        colours=series_colour({"Metrics.Stage 3 Ratio": NAVY}),
    ))

    v.append(table_visual(
        "vSizeAq", 24, 600, 880, 276, 620,
        [
            column("Bank", "Size Band"),
            m("Gross Loans", "Gross loans"),
            m("Stage 2 Ratio", "Stage 2"),
            m("Stage 3 Ratio", "Stage 3"),
            m("Stage 3 Coverage", "Coverage"),
            m("Banks Reporting", "Banks"),
        ],
        sort_by(column("Bank", "Size Band"), "Ascending"),
        "By bank size",
    ))

    v.append(note(
        "vStageNote", 920, 600, 496, 276, 630,
        "Why stage 2 is on the page",
        ["A loan moves to stage 2 when its credit risk has risen significantly since it was "
         "made, before anything has gone wrong. It carries a lifetime loss allowance rather "
         "than a twelve-month one, so it costs capital early.",
         "Stage 3 is the old non-performing loan. By the time it moves, the loss is largely "
         "decided; coverage says how much of it is already provided for.",
         "Stage rows are the only form these items come in - there is no total row - so gross "
         "loans here are the sum of the three stages."],
    ))

    return page("pgQuality", "Asset quality"), v


def page_profit() -> tuple[dict, list[dict]]:
    v: list[dict] = []
    v += masthead(
        "Pl",
        "Earnings, and the year-to-date trap",
        "The P&L in these returns is year to date: March is three months, December twelve. "
        "Full-year figures here are each bank's four-quarter figure for its own financial year. "
        "2025 has no complete year yet, so it is blank rather than half a year.",
        "04 / PROFITABILITY",
    )
    v.append(slicer("vYearPl", SL1_X, SL_Y, SL_W, SL_H, 400, "Period", "Year", "YEAR"))
    v.append(kpi_card("vFyPl", SL2_X, SL_Y, SL_W, SL_H, 410,
                      [m("Financial Year", "Figures for")], value_size=11.0))

    v.append(kpi_card("vKpiPl", 24, 176, 1392, 92, 500, [
        m("Profit FY", "Profit"),
        m("Return on Equity", "Return on equity"),
        m("Cost to Income", "Cost to income"),
        m("Net Interest Share", "Net interest share of income"),
        m("Impairments FY", "Impairment charge"),
    ]))

    v.append(chart(
        "vTrap", "clusteredColumnChart", 24, 284, 452, 300, 600,
        column("Period", "Year"),
        [m("Profit FY", "Full-year profit"), m("Profit, YTD Figures Added", "Four YTD figures added")],
        "Full-year profit, and what adding the quarters gives",
        "Summing a year's four reported figures counts January four times",
        sort=sort_by(column("Period", "Year"), "Ascending"),
        colours=series_colour({"Metrics.Profit FY": NAVY,
                               "Metrics.Profit, YTD Figures Added": BAD}),
        show_legend=True, labels=data_labels(),
    ))

    v.append(chart(
        "vRoe", "columnChart", 492, 284, 452, 300, 610,
        column("Period", "Year"), [m("Return on Equity")],
        "Return on equity by financial year",
        tooltips=[m("Profit FY", "Profit"), m("Year-End Equity", "Equity")],
        sort=sort_by(column("Period", "Year"), "Ascending"),
        colours=series_colour({"Metrics.Return on Equity": NAVY}), labels=data_labels(),
    ))

    v.append(chart(
        "vQuarterly", "columnChart", 960, 284, 456, 300, 620,
        QUARTER_AXIS, [m("Profit in Quarter (Constant Panel)", "Profit in quarter")],
        "Profit in each quarter, de-cumulated",
        "Q3 2022 holds one bank: for the rest, June 2022 is not in the file",
        sort=QUARTER_SORT,
        colours=series_colour({"Metrics.Profit in Quarter (Constant Panel)": GOLD}),
    ))

    v.append(table_visual(
        "vCountryPl", 24, 600, 880, 276, 630,
        [
            column("Bank", "Country"),
            m("Profit FY", "Profit"),
            m("Return on Equity", "ROE"),
            m("Cost to Income", "Cost/income"),
            m("Net Interest Share", "NII share"),
            m("Impairments FY", "Impairments"),
        ],
        sort_by(m("Profit FY")),
        "By country, latest complete financial year",
    ))

    v.append(note(
        "vPlNote", 920, 600, 496, 276, 640,
        "How the quarters were taken apart",
        ["Each quarter's profit is the year-to-date figure less the same bank's previous "
         "quarter, within that bank's own financial year - one bank closes its year in June, "
         "and resetting everyone in January would make its numbers nonsense.",
         "Where the previous quarter is missing the quarter is left blank, not guessed: the "
         "first quarter in the file, a bank's first quarter in the panel, and three banks that "
         "only report their P&L half-yearly.",
         "Full-year figures need none of that, which is why the headline uses them."],
    ))

    return page("pgProfit", "Profitability"), v


def page_banks() -> tuple[dict, list[dict]]:
    v: list[dict] = []
    v += masthead(
        "Bk",
        "Bank by bank",
        "Every bank in the panel at the quarter selected, with the full-year P&L for the "
        "latest complete financial year. Use the country slicer to compare a banking system "
        "bank by bank.",
        "05 / BANKS",
    )
    v.append(slicer("vCountryBk", SL1_X, SL_Y, SL_W, SL_H, 400, "Bank", "Country", "COUNTRY"))
    v.append(slicer("vQuarterBk", SL2_X, SL_Y, SL_W, SL_H, 410, "Period", "Quarter", "QUARTER"))

    v.append(kpi_card("vKpiBk", 24, 176, 1392, 92, 500, [
        m("As At", "Stocks read at"),
        m("Banks Reporting", "Banks"),
        m("CET1 Ratio", "CET1, together"),
        m("CET1 Ratio, Median of Banks", "CET1, median bank"),
        m("Leverage Ratio", "Leverage"),
    ]))

    v.append(table_visual(
        "vBankTable", 24, 284, 1392, 592, 600,
        [
            column("Bank", "Bank"),
            m("Total Assets", "Assets"),
            m("CET1 Ratio", "CET1"),
            m("Tier 1 Ratio", "Tier 1"),
            m("Total Capital Ratio", "Total capital"),
            m("Leverage Ratio", "Leverage"),
            m("RWA Density", "RWA density"),
            m("Stage 3 Ratio", "Stage 3"),
            m("Return on Equity", "ROE"),
            m("Cost to Income", "Cost/income"),
        ],
        sort_by(m("Total Assets")),
        "Every bank, largest first",
        "Legal entity names as the EBA publishes them. Data: EBA EU-wide transparency exercise, "
        "2023 to 2025",
    ))

    return page("pgBanks", "Banks"), v


# --------------------------------------------------------------------------------------------
# Theme and writers
# --------------------------------------------------------------------------------------------


def theme() -> dict:
    return {
        # Desktop caches themes by name, and the name must match the filename exactly.
        "name": THEME_NAME,
        "dataColors": [NAVY, GOLD, SLATE, LIGHT, GOOD, BAD, GOLD_TEXT, MUTED],
        "background": PAPER,
        "foreground": BODY,
        "tableAccent": INK,
        "good": GOOD,
        "neutral": MUTED,
        "bad": BAD,
        "textClasses": {
            "title": {"fontFace": "Segoe UI Semibold", "fontSize": 14, "color": INK},
            "header": {"fontFace": "Segoe UI Semibold", "fontSize": 11, "color": INK},
            "label": {"fontFace": "Segoe UI", "fontSize": 9, "color": BODY},
            "callout": {"fontFace": "Segoe UI", "fontSize": 20, "color": INK},
        },
        "visualStyles": {
            "*": {
                "*": {
                    "background": [{"show": True, "color": {"solid": {"color": CARD}}}],
                    "border": [{"show": True, "color": {"solid": {"color": RULE}}, "radius": 4}],
                    "padding": [{"top": 8, "bottom": 8, "left": 10, "right": 10}],
                    "dropShadow": [{"show": False}],
                }
            }
        },
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # No BOM: a BOM breaks .platform and PBIR parsing. newline="\n" because write_text otherwise
    # uses the platform ending, and the repo is normalised to LF.
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                    newline="\n")


def rmtree_retry(path: Path) -> None:
    """OneDrive intermittently holds a directory handle open; the files are gone by then."""
    for attempt in range(4):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == 3:
                shutil.rmtree(path, ignore_errors=True)
                return
            time.sleep(0.4)


def main() -> None:
    if PAGES.exists():
        rmtree_retry(PAGES)

    builders = [page_capital, page_risk, page_quality, page_profit, page_banks]
    order: list[str] = []
    total_visuals = 0

    for build in builders:
        pg, visuals = build()
        page_dir = PAGES / pg["name"]
        write_json(page_dir / "page.json", pg)
        names = set()
        for node in visuals:
            if node["name"] in names:
                print(f"ERROR: duplicate visual name {node['name']} on {pg['name']}",
                      file=sys.stderr)
                sys.exit(1)
            names.add(node["name"])
            write_json(page_dir / "visuals" / node["name"] / "visual.json", node)
        order.append(pg["name"])
        total_visuals += len(visuals)
        print(f"  {pg['name']:14s} {len(visuals):2d} visuals  ({pg['displayName']})")

    stale = [d for d in PAGES.rglob("visuals/*")
             if d.is_dir() and not (d / "visual.json").exists()]
    for d in stale:
        rmtree_retry(d)
        if d.exists():
            print(f"ERROR: could not remove stale visual directory {d}. "
                  f"Close Power BI Desktop and run again.", file=sys.stderr)
            sys.exit(1)
        print(f"  swept stale visual directory {d.name}")

    write_json(PAGES / "pages.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": order,
        "activePageName": order[0],
    })

    write_json(REPORT / "definition" / "version.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0",
    })

    write_json(REPORT / "definition" / "report.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.3.0/schema.json",
        "themeCollection": {
            "baseTheme": {
                "name": "CY25SU12",
                "reportVersionAtImport": {"visual": "2.12.0", "report": "3.4.0",
                                          "page": "2.3.1"},
                "type": "SharedResources",
            },
            "customTheme": {
                "name": THEME_NAME,
                "reportVersionAtImport": {"visual": "2.12.0", "report": "3.4.0",
                                          "page": "2.3.1"},
                "type": "RegisteredResources",
            },
        },
        "objects": {
            "section": [{"properties": {"verticalAlignment": lit("Top")}}],
            "outspacePane": [{"properties": {"expanded": lit(False)}}],
        },
        "resourcePackages": [
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": THEME_NAME, "path": THEME_NAME, "type": "CustomTheme"},
                       {"name": MARK_NAME, "path": MARK_NAME, "type": "Image"}]},
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": "CY25SU12", "path": "BaseThemes/CY25SU12.json",
                        "type": "BaseTheme"}]},
        ],
        "settings": {"useStylableVisualContainerHeader": True, "useEnhancedTooltips": False},
    })

    RESOURCES.mkdir(parents=True, exist_ok=True)
    write_json(RESOURCES / THEME_NAME, theme())
    shutil.copyfile(ASSETS / "milestone-mark.svg", RESOURCES / MARK_NAME)

    write_json(REPORT / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}},
    })

    write_json(REPORT / ".platform", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Report", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": "8f3c6a21-4e97-4d0b-9c58-2b1e7d4a6f93"},
    })

    write_json(ROOT / f"{NAME}.pbip", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0",
        "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True},
    })

    print(f"\n{len(order)} pages, {total_visuals} visuals written")


if __name__ == "__main__":
    main()
