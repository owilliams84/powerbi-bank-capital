"""Generate the TMDL semantic model - tables, relationships, measures.

TMDL is indentation-sensitive (tabs) and forbids blank lines inside an object, and every object
needs a stable lineageTag. This owns the format and the tags (uuid5 of the object's path, so
re-running never churns them), and the table definitions below read as a schema.

    python etl/build_model.py            # partitions read the CSVs from GitHub over HTTPS
    python etl/build_model.py --local    # partitions read data/ on this machine (offline)

The fact is one file per EBA exercise, loaded as one partition each.

Rewrites <model>/definition/ from scratch every run.
"""

from __future__ import annotations

import argparse
import shutil
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "Bank Capital.SemanticModel"
DEFN = MODEL / "definition"
DATA = ROOT / "data"

RAW = "https://raw.githubusercontent.com/owilliams84/powerbi-bank-capital/main/data/"
NS = uuid.UUID("c4a7d2e9-1f36-4b85-9e0c-7a3d5b6f8c21")
EXERCISES = ["2023", "2024", "2025"]


def tag(*parts: str) -> str:
    return str(uuid.uuid5(NS, "bankcap:" + ":".join(parts)))


def q(name: str) -> str:
    """Quote a TMDL identifier when it needs it."""
    return name if name.replace("_", "").isalnum() else f"'{name}'"


def doc(text: str | None, indent: int) -> list[str]:
    if not text:
        return []
    pad = "\t" * indent
    return [f"{pad}/// {para}".rstrip() for para in text.strip("\n").split("\n")]


def col(name, source, dtype, **o):
    return dict(name=name, source=source, dtype=dtype, **o)


INT_T, TXT_T, NUM_T, DATE_T = "Int64.Type", "type text", "type number", "type date"

TABLES = {
    "Period": dict(
        file="dim_period.csv",
        doc="The twelve quarter-ends the three exercises cover, September 2022 to June 2025. Each\n"
            "exercise publishes four quarters; they abut without overlapping.\n"
            "\n"
            "Not a date table on purpose. Supervisory data is quarter-end snapshots, and every\n"
            "stock measure here reads the last quarter in view rather than walking a calendar.",
        columns=[
            col("Period", "Period", "int64", key=True, hidden=True, format="0"),
            col("Quarter End", "QuarterEnd", "dateTime", format="d mmm yyyy"),
            col("Quarter", "Label", "string", sortBy="Period Sort"),
            col("Year", "Year", "int64", format="0"),
            col("Quarter No", "Quarter", "int64", hidden=True, format="0"),
            col("Period Sort", "Sort", "int64", hidden=True, format="0"),
            col("Exercise", "Exercise", "int64", format="0",
                doc="The EBA transparency exercise that published this quarter."),
        ],
        types={"Period": INT_T, "QuarterEnd": DATE_T, "Label": TXT_T, "Year": INT_T,
               "Quarter": INT_T, "Sort": INT_T, "Exercise": INT_T},
    ),
    "Bank": dict(
        file="dim_bank.csv",
        doc="One row per bank that appears in any of the three exercises - 129 of them.\n"
            "\n"
            "The EBA's 'All other banks' aggregate, published beside them under an LEI of twenty\n"
            "X's, is dropped in the ETL: it is not a bank.\n"
            "\n"
            "'In Constant Panel' is Yes for the 101 banks that report CET1 in all twelve quarters.\n"
            "Trend measures use it, because a sector ratio computed over whoever reported that\n"
            "quarter moves every time a bank joins or leaves.",
        columns=[
            col("LEI", "LEI", "string", key=True,
                doc="Legal Entity Identifier - the only identifier the EBA publishes."),
            col("Bank", "Bank", "string"),
            col("Country Code", "CountryCode", "string"),
            col("Country", "Country", "string"),
            col("Financial Year End", "FinancialYearEnd", "string",
                doc="31 December for every bank but one, whose year ends on 30 June. The three\n"
                    "exercises write it three different ways; the ETL normalises them."),
            col("Size Band", "SizeBand", "string", sortBy="Size Band Sort",
                doc="By total assets at the bank's latest reported quarter."),
            col("Size Band Sort", "SizeBandSort", "int64", hidden=True, format="0"),
            col("In All Exercises", "InAllExercises", "string"),
            col("In Constant Panel", "InConstantPanel", "string"),
            col("First Period", "FirstPeriod", "int64", hidden=True, format="0"),
            col("Last Period", "LastPeriod", "int64", hidden=True, format="0"),
        ],
        types={"LEI": TXT_T, "Bank": TXT_T, "CountryCode": TXT_T, "Country": TXT_T,
               "FinancialYearEnd": TXT_T, "SizeBand": TXT_T, "SizeBandSort": INT_T,
               "InAllExercises": TXT_T, "InConstantPanel": TXT_T, "FirstPeriod": INT_T,
               "LastPeriod": INT_T},
    ),
    "Item": dict(
        file="dim_item.csv",
        doc="The 158 supervisory line items used, keyed on the 2025 item code.\n"
            "\n"
            "The EBA renumbers every item every year - CET1 capital is 2320102, then 2420102,\n"
            "then 2520102. The ETL maps the earlier codes forward through the 2025 data dictionary\n"
            "and fails if any row will not map, so a series here is one item across all three\n"
            "exercises, not three items that happen to share a label.",
        columns=[
            col("Item Key", "ItemKey", "int64", key=True, format="0"),
            col("Item", "Label", "string"),
            col("Template", "Template", "string",
                doc="Capital, Leverage, RWA OV1, P&L, Assets or Liabilities."),
            col("Is Ratio", "IsRatio", "string",
                doc="Yes for the reported ratios. Nothing on the report sums or averages these;\n"
                    "every ratio shown is recomputed from its numerator and denominator."),
            col("RWA Component", "RwaComponent", "string", sortBy="RWA Sort",
                doc="The ten lines of OV1 that add up to total risk exposure - the top-level risk\n"
                    "types plus the 2025 output-floor adjustment. Blank for everything else,\n"
                    "including the 'of which' lines that would double count."),
            col("RWA Sort", "RwaSort", "int64", hidden=True, format="0"),
            col("Basis", "Basis", "string",
                doc="Point in time, Ratio, or Year to date. The P&L is year to date."),
            col("Item Sort", "ItemSort", "int64", hidden=True, format="0"),
        ],
        types={"ItemKey": INT_T, "Label": TXT_T, "Template": TXT_T, "IsRatio": TXT_T,
               "RwaComponent": TXT_T, "RwaSort": INT_T, "Basis": TXT_T, "ItemSort": INT_T},
    ),
    "Stage": dict(
        file="dim_stage.csv",
        doc="IFRS 9 impairment stage. Only the gross-carrying-amount and accumulated-impairment\n"
            "lines are staged; everything else is 'Not staged'.",
        columns=[
            col("Stage Key", "StageKey", "int64", key=True, hidden=True, format="0"),
            col("Stage", "Stage", "string", sortBy="Stage Key"),
            col("Stage Meaning", "StageMeaning", "string"),
        ],
        types={"StageKey": INT_T, "Stage": TXT_T, "StageMeaning": TXT_T},
    ),
    "Prudential": dict(
        files=[f"fact_prudential_{y}.csv" for y in EXERCISES],
        partition_names=EXERCISES,
        nullable=["Quarterly"],
        doc="One row per bank, quarter, item and IFRS 9 stage. EUR millions; ratios as decimals.\n"
            "\n"
            "Two amount columns, because the P&L is year to date. 'Amount' is as reported.\n"
            "'Quarterly' is the P&L de-cumulated against the same bank's previous quarter within\n"
            "its own financial year, and is left blank where that cannot be done honestly - the\n"
            "first quarter in the file, a bank's first quarter in the panel, and three banks that\n"
            "report their P&L half-yearly. For stocks the two columns are the same.",
        columns=[
            col("LEI", "LEI", "string", hidden=True),
            col("Period", "Period", "int64", hidden=True, format="0"),
            col("Item Key", "ItemKey", "int64", hidden=True, format="0"),
            col("Stage Key", "StageKey", "int64", hidden=True, format="0"),
            col("Quarters In YTD", "QuartersInYTD", "int64", hidden=True, format="0",
                doc="How many quarters a year-to-date P&L figure spans. 4 is a full year."),
            col("Amount", "Amount", "double", hidden=True, format="#,0.0"),
            col("Quarterly", "Quarterly", "double", hidden=True, format="#,0.0"),
        ],
        types={"LEI": TXT_T, "Period": INT_T, "ItemKey": INT_T, "StageKey": INT_T,
               "QuartersInYTD": INT_T, "Amount": NUM_T, "Quarterly": NUM_T},
    ),
}

RELATIONSHIPS = [
    ("Bank to Prudential", "Prudential.LEI", "Bank.LEI"),
    ("Period to Prudential", "Prudential.Period", "Period.Period"),
    ("Item to Prudential", "Prudential.'Item Key'", "Item.'Item Key'"),
    ("Stage to Prudential", "Prudential.'Stage Key'", "Stage.'Stage Key'"),
]

# The data is EUR millions; every money measure divides by a thousand and reads in billions.
# Done in the measure, not the format string: Power BI ignores a scaling comma that is followed
# by a literal, so "€#,0,bn" rendered CET1 as €1,605,203bn.
EUR_BN = "€#,0\\b\\n"
INT, PCT1, PCT2 = "#,0", "0.0%", "0.00%"

AMT = "SUM('Prudential'[Amount]) / 1000"


def item(key: int) -> str:
    return f"'Item'[Item Key] = {key}"


def at_latest(expr: str, *filters: str) -> str:
    """A stock read at the last quarter in view. Balance-sheet and capital figures are
    point-in-time: adding June to March double counts the bank."""
    f = "".join(f",\n        {x}" for x in filters)
    return ("VAR p = MAX('Period'[Period Sort])\n"
            "RETURN\n"
            "    CALCULATE(\n"
            f"        {expr}{f},\n"
            "        'Period'[Period Sort] = p\n"
            "    )")


# The financial year in view: the latest calendar year that has a fourth quarter in the current
# filter. 2025 has none - the file stops in June - so full-year measures go blank there rather
# than reporting a single bank's June year-end as the sector.
FY = "VAR y = CALCULATE(MAX('Period'[Year]), 'Period'[Quarter No] = 4)\n"


def full_year(key: int) -> str:
    """A P&L line for the financial year ending in year y: the YTD figure that spans four
    quarters. For 30 of 31 December banks that is the December figure; for the June-year-end
    bank it is June's - which is why this filters on Quarters In YTD and not on December."""
    return (FY + "RETURN\n"
            "    CALCULATE(\n"
            f"        {AMT},\n"
            f"        {item(key)},\n"
            "        'Prudential'[Quarters In YTD] = 4,\n"
            "        'Period'[Year] = y\n"
            "    )")


PANEL = "KEEPFILTERS('Bank'[In Constant Panel] = \"Yes\")"

MEASURES = [
    # ---- capital stocks
    ("CET1 Capital", at_latest(AMT, item(2520102)), EUR_BN,
     "Common Equity Tier 1 after deductions and transitional adjustments, at the last quarter\n"
     "in view."),
    ("Tier 1 Capital", at_latest(AMT, item(2520133)), EUR_BN, None),
    ("Own Funds", at_latest(AMT, item(2520101)), EUR_BN, "Total capital: Tier 1 plus Tier 2."),
    ("Total Risk Exposure", at_latest(AMT, item(2520138)), EUR_BN,
     "Risk-weighted assets - the denominator of every capital ratio."),
    ("RWA Pre-Floor", at_latest(AMT, item(2520154)), EUR_BN,
     "Risk exposure before the CRR3 output floor. Reported from 2025 only."),
    ("Total Assets", at_latest(AMT, item(2521010)), EUR_BN, None),
    ("Total Equity", at_latest(AMT, item(2521216)), EUR_BN, "Accounting equity, FINREP."),
    ("Leverage Exposure", at_latest(AMT, item(2520903)), EUR_BN, None),
    ("Tier 1 for Leverage", at_latest(AMT, item(2520901)), EUR_BN, None),
    ("Banks Reporting", at_latest("DISTINCTCOUNT('Prudential'[LEI])", item(2520102)), INT,
     "Banks with a CET1 figure in the last quarter in view."),

    # ---- ratios, all recomputed
    ("CET1 Ratio", "DIVIDE([CET1 Capital], [Total Risk Exposure])", PCT1,
     "Capital over risk-weighted assets, summed first and divided once - the ratio of the\n"
     "sector, or of whatever is in view. The reported CET1 ratio is never averaged."),
    ("Tier 1 Ratio", "DIVIDE([Tier 1 Capital], [Total Risk Exposure])", PCT1, None),
    ("Total Capital Ratio", "DIVIDE([Own Funds], [Total Risk Exposure])", PCT1, None),
    ("Leverage Ratio", "DIVIDE([Tier 1 for Leverage], [Leverage Exposure])", PCT2,
     "Tier 1 over total exposure, unweighted. The 3% minimum does not care about risk weights."),
    ("RWA Density", "DIVIDE([Total Risk Exposure], [Total Assets])", PCT1,
     "Risk-weighted assets per euro of balance sheet. Low density is what an internal model\n"
     "buys, and what the output floor is there to limit."),
    ("CET1 Ratio, Average of Banks",
     "AVERAGEX(\n"
     "    FILTER(VALUES('Bank'[LEI]), NOT ISBLANK([CET1 Ratio])),\n"
     "    [CET1 Ratio]\n"
     ")", PCT1,
     "Each bank's ratio, averaged with equal weight. What you get by averaging the reported\n"
     "ratio column - and 6.5 points above the sector's actual ratio at June 2025, because the\n"
     "small banks carry the most capital per euro of risk and each one counts as much as the\n"
     "largest. Kept so the report can show the two side by side."),
    ("CET1 Ratio, Median of Banks",
     "MEDIANX(\n"
     "    FILTER(VALUES('Bank'[LEI]), NOT ISBLANK([CET1 Ratio])),\n"
     "    [CET1 Ratio]\n"
     ")", PCT1, "The typical bank."),
    ("Average Minus Aggregate",
     "IF(\n"
     "    NOT ISBLANK([CET1 Ratio]),\n"
     "    [CET1 Ratio, Average of Banks] - [CET1 Ratio]\n"
     ")", PCT1,
     "How far the equal-weighted average overstates the sector ratio, in percentage points."),

    # ---- trend on a fixed panel
    ("CET1 Ratio (Constant Panel)", f"CALCULATE([CET1 Ratio], {PANEL})", PCT1,
     "The sector ratio over the 101 banks present in every quarter, so a quarter-on-quarter\n"
     "move is the banks moving, not the membership."),
    ("CET1 Ratio, Average of Banks (Constant Panel)",
     f"CALCULATE([CET1 Ratio, Average of Banks], {PANEL})", PCT1, None),
    ("Leverage Ratio (Constant Panel)", f"CALCULATE([Leverage Ratio], {PANEL})", PCT2, None),
    ("CET1 Ratio a Year Earlier",
     "VAR p = MAX('Period'[Period Sort])\n"
     "RETURN\n"
     f"    CALCULATE([CET1 Ratio], {PANEL}, REMOVEFILTERS('Period'), 'Period'[Period Sort] = p - 4)",
     PCT1, "Constant panel, four quarters before the last one in view."),
    ("CET1 Change on Year",
     "VAR Earlier = [CET1 Ratio a Year Earlier]\n"
     "RETURN\n"
     f"    IF(NOT ISBLANK(Earlier), [CET1 Ratio (Constant Panel)] - Earlier)", "+0.0%;-0.0%;0.0%",
     "Percentage points, constant panel."),

    # ---- risk-weighted assets and the output floor
    ("RWA by Component", at_latest(AMT, "KEEPFILTERS('Item'[RWA Component] <> \"\")"), EUR_BN,
     "The ten OV1 lines that add to total risk exposure. They reconcile to the reported total\n"
     "for every bank in every quarter, to a thousandth of a million."),
    ("RWA Share",
     "DIVIDE([RWA by Component], CALCULATE([RWA by Component], REMOVEFILTERS('Item')))", PCT1,
     None),
    ("CET1 Ratio Pre-Floor",
     "IF(NOT ISBLANK([RWA Pre-Floor]), DIVIDE([CET1 Capital], [RWA Pre-Floor]))", PCT1,
     "The ratio before the output floor is applied. 2025 onwards."),
    ("Output Floor Cost",
     "IF(NOT ISBLANK([CET1 Ratio Pre-Floor]), [CET1 Ratio Pre-Floor] - [CET1 Ratio])",
     "0.00%", "Ratio points lost to the floor. In 2025 the floor binds on one bank."),

    # ---- asset quality: loans and advances at amortised cost
    ("Gross Loans", at_latest(AMT, item(2521019)), EUR_BN,
     "Gross carrying amount, loans and advances at amortised cost, all three stages."),
    ("Stage 2 Loans", at_latest(AMT, item(2521019), "'Stage'[Stage Key] = 2"), EUR_BN, None),
    ("Stage 3 Loans", at_latest(AMT, item(2521019), "'Stage'[Stage Key] = 3"), EUR_BN,
     "Credit-impaired - the IFRS 9 successor to the non-performing loan."),
    ("Stage 2 Ratio", "DIVIDE([Stage 2 Loans], [Gross Loans])", PCT2,
     "Loans with a significant increase in credit risk since origination. The early-warning\n"
     "line: stage 2 moves before stage 3 does."),
    ("Stage 3 Ratio", "DIVIDE([Stage 3 Loans], [Gross Loans])", PCT2, None),
    ("Stage 3 Allowance", at_latest(AMT, item(2521029), "'Stage'[Stage Key] = 3"), EUR_BN,
     "Accumulated impairment on stage 3 loans. Reported negative."),
    ("Stage 3 Coverage", "DIVIDE(-[Stage 3 Allowance], [Stage 3 Loans])", PCT1,
     "How much of the impaired book is already provided for."),

    # ---- profitability, by financial year
    ("Interest Income FY", full_year(2520301), EUR_BN, None),
    ("Interest Expense FY", full_year(2520304), EUR_BN, None),
    ("Net Interest Income FY", "[Interest Income FY] - [Interest Expense FY]", EUR_BN, None),
    ("Operating Income FY", full_year(2520316), EUR_BN, "Total operating income, net."),
    ("Operating Expenses FY",
     FY + "RETURN\n"
     "    CALCULATE(\n"
     f"        {AMT},\n"
     "        'Item'[Item Key] IN {2520317, 2520318},\n"
     "        'Prudential'[Quarters In YTD] = 4,\n"
     "        'Period'[Year] = y\n"
     "    )", EUR_BN, "Administrative expenses and depreciation. Reported positive."),
    ("Cost to Income", "DIVIDE([Operating Expenses FY], [Operating Income FY])", PCT1, None),
    ("Impairments FY", full_year(2520324), EUR_BN,
     "Impairment on financial assets not at fair value - the P&L charge for credit losses."),
    ("Profit FY", full_year(2520335), EUR_BN, "Profit or loss for the financial year."),
    ("Year-End Equity",
     FY + "RETURN\n"
     "    CALCULATE([Total Equity], 'Period'[Year] = y, 'Period'[Quarter No] = 4)", EUR_BN,
     None),
    ("Return on Equity", "DIVIDE([Profit FY], [Year-End Equity])", PCT1,
     "Full-year profit over year-end equity."),
    ("Net Interest Share", "DIVIDE([Net Interest Income FY], [Operating Income FY])", PCT1,
     None),
    ("Profit, YTD Figures Added",
     FY + "RETURN\n"
     f"    CALCULATE({AMT}, {item(2520335)}, 'Period'[Year] = y)", EUR_BN,
     "What adding up a year's four reported P&L figures gives: March once, June twice, September\n"
     "three times, December's own. It reads about two and a half times the real profit. Kept\n"
     "because it is the easiest mistake to make with this file, and the report shows it."),
    ("YTD Overstatement", "DIVIDE([Profit, YTD Figures Added] - [Profit FY], [Profit FY])", "0%",
     None),
    ("Profit in Quarter", f"CALCULATE(SUM('Prudential'[Quarterly]) / 1000, {item(2520335)})", EUR_BN,
     "De-cumulated: this quarter's profit alone. Blank where it cannot be derived."),
    ("Profit in Quarter (Constant Panel)", f"CALCULATE([Profit in Quarter], {PANEL})", EUR_BN,
     None),

    # ---- labels
    ("As At",
     "VAR p = MAX('Period'[Period Sort])\n"
     "RETURN\n"
     "    LOOKUPVALUE('Period'[Quarter], 'Period'[Period Sort], p)", None,
     "The quarter every stock on the page is read at."),
    ("Financial Year",
     FY + "RETURN\n"
     "    IF(ISBLANK(y), \"No complete year\", \"FY \" & y)", None, None),
]


def m_partition(name: str, file: str, spec: dict, local: bool) -> list[str]:
    if local:
        path = str((DATA / file).resolve()).replace("\\", "\\\\")
        src = f'File.Contents("{path}")'
    else:
        src = f'Web.Contents("{RAW}{file}")'
    n = len(spec["types"])
    types = ", ".join(f'{{"{c}", {t}}}' for c, t in spec["types"].items())
    lines = [
        f"\tpartition {q(name)} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        f'\t\t\t\t    Source = Csv.Document({src}, [Delimiter=",", Columns={n}, '
        f'Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
        '\t\t\t\t    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),',
    ]
    step = '#"Promoted Headers"'
    if spec.get("nullable"):
        # An empty CSV cell arrives as "", and "" does not convert to a number - it becomes a
        # cell error. Make it null first so an underivable quarter stays blank.
        cols = ", ".join(f'"{c}"' for c in spec["nullable"])
        lines.append(f'\t\t\t\t    #"Blanks to Null" = Table.ReplaceValue({step}, "", null, '
                     f'Replacer.ReplaceValue, {{{cols}}}),')
        step = '#"Blanks to Null"'
    lines += [
        f'\t\t\t\t    #"Applied Types" = Table.TransformColumnTypes({step}, {{{types}}})',
        "\t\t\t\tin",
        '\t\t\t\t    #"Applied Types"',
    ]
    return lines


def write_table(name: str, spec: dict, local: bool) -> None:
    lines: list[str] = []
    lines += doc(spec.get("doc"), 0)
    lines.append(f"table {q(name)}")
    lines.append(f"\tlineageTag: {tag('table', name)}")
    for c in spec["columns"]:
        lines.append("")
        lines += doc(c.get("doc"), 1)
        lines.append(f"\tcolumn {q(c['name'])}")
        lines.append(f"\t\tdataType: {c['dtype']}")
        if c.get("hidden"):
            lines.append("\t\tisHidden")
        if c.get("key"):
            lines.append("\t\tisKey")
        if c.get("format"):
            lines.append(f"\t\tformatString: {c['format']}")
        lines.append(f"\t\tlineageTag: {tag('column', name, c['name'])}")
        lines.append("\t\tsummarizeBy: none")
        lines.append(f"\t\tsourceColumn: {c['source']}")
        if c.get("sortBy"):
            lines.append(f"\t\tsortByColumn: {q(c['sortBy'])}")
    if "files" in spec:
        for pname, f in zip(spec["partition_names"], spec["files"]):
            lines.append("")
            lines += m_partition(f"{name} {pname}", f, spec, local)
    else:
        lines.append("")
        lines += m_partition(name, spec["file"], spec, local)
    lines.append("")
    lines.append("\tannotation PBI_ResultType = Table")
    write(DEFN / "tables" / f"{name}.tmdl", lines)


def write_metrics() -> None:
    lines: list[str] = []
    lines += doc("Measure-only table. Nothing here stores data; the hidden column exists because\n"
                 "a table needs one. Every number on the report comes from here.", 0)
    lines.append("table Metrics")
    lines.append(f"\tlineageTag: {tag('table', 'Metrics')}")
    for name, dax, fmt, d in MEASURES:
        lines.append("")
        lines += doc(d, 1)
        body = dax.split("\n")
        if len(body) == 1:
            lines.append(f"\tmeasure {q(name)} = {body[0]}")
        else:
            lines.append(f"\tmeasure {q(name)} =")
            for b in body:
                lines.append(("\t\t\t" + b) if b.strip() else "\t\t\t")
        if fmt:
            lines.append(f"\t\tformatString: {fmt}")
        lines.append(f"\t\tlineageTag: {tag('measure', name)}")
    lines.append("")
    lines.append("\tcolumn Column")
    lines.append("\t\tdataType: string")
    lines.append("\t\tisHidden")
    lines.append(f"\t\tlineageTag: {tag('column', 'Metrics', 'Column')}")
    lines.append("\t\tsummarizeBy: none")
    lines.append("\t\tsourceColumn: Column")
    lines.append("")
    lines.append("\tpartition Metrics = m")
    lines.append("\t\tmode: import")
    lines.append("\t\tsource =")
    lines.append("\t\t\t\tlet")
    lines.append('\t\t\t\t    Source = #table(type table [Column = text], {})')
    lines.append("\t\t\t\tin")
    lines.append("\t\t\t\t    Source")
    lines.append("")
    lines.append("\tannotation PBI_ResultType = Table")
    write(DEFN / "tables" / "Metrics.tmdl", lines)


def write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_json(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip("\n") + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true", help="read data/ from disk, not GitHub")
    args = ap.parse_args()

    if DEFN.exists():
        for attempt in range(5):
            try:
                shutil.rmtree(DEFN)
                break
            except PermissionError:
                if attempt == 4:
                    shutil.rmtree(DEFN, ignore_errors=True)
                else:
                    time.sleep(0.5)

    for name, spec in TABLES.items():
        write_table(name, spec, args.local)
    write_metrics()

    write(DEFN / "database.tmdl", ["database", "\tcompatibilityLevel: 1606"])

    order = ", ".join(f'"{t}"' for t in TABLES)
    write(DEFN / "model.tmdl", [
        "model Model",
        "\tculture: en-GB",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tdiscourageImplicitMeasures",
        "\tsourceQueryCulture: en-US",
        "",
        f"annotation PBI_QueryOrder = [{order}]",
        "",
        "annotation __PBI_TimeIntelligenceEnabled = 0",
        "",
        'annotation PBI_ProTooling = ["DevMode"]',
        "",
    ] + [f"ref table {q(t)}" for t in list(TABLES) + ["Metrics"]])

    rel_lines: list[str] = []
    for i, (name, frm, to) in enumerate(RELATIONSHIPS):
        if i:
            rel_lines.append("")
        rel_lines += [f"relationship {q(name)}", f"\tfromColumn: {frm}", f"\ttoColumn: {to}"]
    write(DEFN / "relationships.tmdl", rel_lines)

    write_json(MODEL / "definition.pbism", """
{
  "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
  "version": "4.2",
  "settings": {
    "qnaEnabled": true
  }
}""")
    write_json(MODEL / ".platform", f"""
{{
  "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
  "metadata": {{
    "type": "SemanticModel",
    "displayName": "Bank Capital"
  }},
  "config": {{
    "version": "2.0",
    "logicalId": "{tag('platform', 'model')}"
  }}
}}""")

    n_cols = sum(len(s["columns"]) for s in TABLES.values())
    print(f"{len(TABLES) + 1} tables, {n_cols} columns, {len(MEASURES)} measures, "
          f"{len(RELATIONSHIPS)} relationships -> {MODEL.name} "
          f"({'local files' if args.local else 'GitHub raw'})")


if __name__ == "__main__":
    main()
