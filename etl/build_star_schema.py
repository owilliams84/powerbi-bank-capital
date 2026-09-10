"""Turn three EBA transparency exercises into one prudential star schema.

Source: the EBA EU-wide transparency exercise, full database - 2023, 2024 and 2025 editions,
https://www.eba.europa.eu/risk-and-data-analysis/risk-analysis/eu-wide-transparency-exercise
"Reproduction of all EBA material on this site is authorised, provided the source is
acknowledged." Bank-level data drawn from COREP and FINREP supervisory returns.

    python etl/build_star_schema.py --source <folder holding 2023/ 2024/ 2025/>

Each year folder needs tr_oth.csv, TR_Metadata.xlsx and SDD.xlsx. Writes data/ and
data/quality_report.json.

Four things this has to get right, none of which the files announce:

1.  **Item codes are renumbered every year.** CET1 capital is 2320102 in 2023, 2420102 in 2024
    and 2520102 in 2025. Stacking the three files without the data dictionary gives three
    unrelated series. The 2025 SDD maps every item back to its earlier codes; the build keys
    everything on the 2025 code and fails if a row cannot be mapped.

2.  **The P&L is year-to-date.** September is nine months, December is twelve, March is three.
    Adding the four quarters of a year counts January's income four times. Every P&L row is
    de-cumulated against the same bank's previous quarter - by that bank's own financial year,
    because one bank closes its year in June.

3.  **The Key Metrics template was withdrawn in 2025**, taking the headline CET1 and leverage
    ratios with it. They are not needed: the Capital template carries CET1, Tier 1, total
    capital and the total risk exposure amount in every year, and a ratio computed from those
    matches the reported one to six decimal places. The model computes ratios; it never stores
    one where it could be summed.

4.  **The panel is not constant.** Banks join and leave between exercises. Any sector trend
    computed over whoever happened to report that quarter moves with the membership, so every
    bank carries a constant-panel flag - CET1 reported in all twelve quarters - and the trend
    measures use it.

Amounts are EUR millions (BNP Paribas' total assets at June 2025 read 2,573,934). Ratios are
decimals.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LF = "\n"
YEARS = ["2023", "2024", "2025"]

# Templates used. Key Metrics is excluded on purpose (point 3 above); Assets and Liabilities
# supply the IFRS 9 stages, total assets and equity.
SHEETS = ["Capital", "Leverage", "RWA OV1", "P&L", "Assets", "Liabilities"]


def write_csv(df: pd.DataFrame, name: str) -> None:
    path = DATA / name
    df.to_csv(path, index=False, lineterminator=LF)
    print("  %-26s %8d rows  %7.1f KB" % (name, len(df), path.stat().st_size / 1024))


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
YEAR_ENDS = {3: "31 March", 6: "30 June", 9: "30 September", 12: "31 December"}

# The top-level lines of the OV1 risk-weighted-asset template, plus the output floor
# adjustment. Everything else in OV1 is an "of which" and would double count. These ten add up
# to the reported total for every bank in every quarter.
RWA_COMPONENTS = {
    "2520201": ("Credit risk", 1), "2520206": ("Counterparty credit risk", 2),
    "2520207": ("CVA", 3), "2520208": ("Settlement", 4), "2520209": ("Securitisation", 5),
    "2520210": ("Market risk", 6), "2520214": ("Large exposures", 7),
    "2520215": ("Operational risk", 8), "2520219": ("Other", 9),
    "2520222": ("Output floor", 10),
}

# Total assets at the bank's latest reported quarter, EUR millions.
SIZE_BANDS = [(500_000, "Over €500bn", 1), (150_000, "€150bn to €500bn", 2),
              (50_000, "€50bn to €150bn", 3), (0, "Under €50bn", 4)]


def year_end(v) -> str:
    """Each edition writes the financial year-end its own way - '31/12' in 2023, a timestamp in
    2024, '31-Dec' in 2025."""
    if pd.isna(v):
        return ""
    if hasattr(v, "month"):
        return YEAR_ENDS[v.month]
    tail = str(v).strip().lower().replace("-", "/").split("/")[-1]
    return YEAR_ENDS[int(tail) if tail.isdigit() else MONTHS[tail[:3]]]


def size_band(total_assets: float) -> tuple[str, int]:
    for edge, label, sort in SIZE_BANDS:
        if total_assets >= edge:
            return label, sort
    return "", 0


def code(v) -> str | None:
    if pd.isna(v):
        return None
    s = str(v).strip()
    return s[:-2] if s.endswith(".0") else s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    args = ap.parse_args()
    src = Path(args.source)
    DATA.mkdir(exist_ok=True)
    q: dict[str, object] = {}

    # ------------------------------------------------------------------ the item map
    sdd = pd.read_excel(src / "2025" / "SDD.xlsx", header=1)
    sdd = sdd[sdd["CSV"].astype(str).str.contains("tr_oth")].copy()
    sdd["i25"] = sdd["Item"].map(code)
    sdd["i24"] = sdd["Item_TR_2024"].map(code)
    sdd["i23"] = sdd["Item_TR_2023"].map(code)
    to25 = {"2025": dict(zip(sdd["i25"], sdd["i25"])),
            "2024": {k: v for k, v in zip(sdd["i24"], sdd["i25"]) if k},
            "2023": {k: v for k, v in zip(sdd["i23"], sdd["i25"]) if k}}

    # ------------------------------------------------------------------ the three exercises
    frames, names = [], {}
    for y in YEARS:
        o = pd.read_csv(src / y / "tr_oth.csv", dtype=str)
        q[f"rows_{y}"] = int(len(o))
        q[f"key_metrics_rows_dropped_{y}"] = int((o.Sheet == "Key metrics").sum())
        o = o[o.Sheet.isin(SHEETS)].copy()
        o["ItemKey"] = o["Item"].map(to25[y])
        unmapped = o[o["ItemKey"].isna()]
        if len(unmapped):
            raise SystemExit(f"{y}: {unmapped.Item.nunique()} items with no 2025 code, e.g. "
                             f"{unmapped[['Item', 'Label']].drop_duplicates().head(3).values}")
        o["Exercise"] = y
        frames.append(o)
        inst = pd.read_excel(src / y / "TR_Metadata.xlsx", sheet_name="List of Institutions",
                             header=1)
        for r in inst.itertuples():
            names[r.LEI_Code] = (r.Name, r.Country, r.Desc_country, year_end(r.Fin_year_end))
    f = pd.concat(frames, ignore_index=True)
    del frames

    # One LEI is twenty X's: the EBA's "All other banks" aggregate, published beside the named
    # banks in the same file. It is not a bank. Dropped, and counted.
    agg = f["LEI_Code"].str.fullmatch("X+")
    q["aggregate_rows_dropped"] = int(agg.sum())
    f = f[~agg].copy()

    f["Amount"] = f["Amount"].astype(float)
    for c in ("ASSETS_FV", "ASSETS_Stages", "Exposure", "Financial_instruments", "n_quarters"):
        f[c] = f[c].astype(int)
    keys = ["LEI_Code", "Period", "ItemKey", "ASSETS_FV", "ASSETS_Stages", "Exposure",
            "Financial_instruments"]
    dups = f.duplicated(keys, keep=False)
    q["duplicate_rows_across_exercises"] = int(dups.sum())
    if dups.any():
        raise SystemExit(f"{int(dups.sum())} rows collide across exercises - periods overlap")

    # Breakdown rows: fair-value levels 1-3 under the asset lines (level 0 is their total), and
    # one liabilities item split by counterparty and instrument. Kept, they would be summed into
    # the totals they break down. Only the IFRS 9 stages stay, because the stage rows have no
    # total row beside them - they are the only form those items come in.
    breakdown = (f["ASSETS_FV"] != 0) | (f["Exposure"] != 0) | (f["Financial_instruments"] != 0)
    q["breakdown_rows_dropped"] = int(breakdown.sum())
    f = f[~breakdown].copy()

    # ------------------------------------------------------------------ banks
    lei = sorted(f.LEI_Code.unique())
    present = f.groupby("LEI_Code")["Exercise"].nunique()
    periods = f.groupby("LEI_Code")["Period"].agg(["min", "max"])
    # Appearing in all three exercises is not the same as reporting every quarter. The trend
    # panel is the stricter test: CET1 reported in all twelve quarters.
    cet1_quarters = f[f.ItemKey == "2520102"].groupby("LEI_Code")["Period"].nunique()
    n_periods = f["Period"].nunique()
    assets = f[f.ItemKey == "2521010"].sort_values("Period").groupby("LEI_Code")["Amount"].last()
    rows = []
    for l in lei:
        band, band_sort = size_band(assets.get(l, 0.0))
        rows.append(dict(
            LEI=l, Bank=names[l][0], CountryCode=names[l][1], Country=names[l][2],
            FinancialYearEnd=names[l][3],
            SizeBand=band, SizeBandSort=band_sort,
            InAllExercises="Yes" if present[l] == len(YEARS) else "No",
            InConstantPanel="Yes" if cet1_quarters.get(l, 0) == n_periods else "No",
            FirstPeriod=periods.loc[l, "min"], LastPeriod=periods.loc[l, "max"],
        ))
    dim_bank = pd.DataFrame(rows)
    q["banks"] = int(len(dim_bank))
    q["banks_in_all_three"] = int((dim_bank.InAllExercises == "Yes").sum())
    q["banks_in_constant_panel"] = int((dim_bank.InConstantPanel == "Yes").sum())
    q["banks_by_size_band"] = dim_bank.groupby("SizeBand").size().to_dict()
    q["non_calendar_year_banks"] = dim_bank.loc[
        dim_bank.FinancialYearEnd != "31 December", ["Bank", "FinancialYearEnd"]
    ].values.tolist()
    q["country_codes"] = sorted(dim_bank.CountryCode.dropna().unique().tolist())

    # ------------------------------------------------------------------ periods
    ps = sorted(f.Period.unique())
    dim_period = pd.DataFrame([dict(
        Period=p, QuarterEnd=(pd.Period(p[:4] + "-" + p[4:], "M").end_time.date().isoformat()),
        Label=f"Q{(int(p[4:]) - 1) // 3 + 1} {p[:4]}", Year=int(p[:4]),
        Quarter=(int(p[4:]) - 1) // 3 + 1, Sort=i,
        Exercise=f.loc[f.Period == p, "Exercise"].iloc[0],
    ) for i, p in enumerate(ps, start=1)])
    q["periods"] = ps

    # ------------------------------------------------------------------ de-cumulate the P&L
    # Quarterly = YTD this quarter - YTD the previous quarter, within the bank's financial
    # year. n_quarters says how many quarters the YTD figure spans; 1 means it already is a
    # quarter. The previous quarter must exist and must span exactly one fewer quarter, or the
    # quarterly figure is left blank rather than guessed.
    pl = f["Sheet"] == "P&L"
    f["PeriodSort"] = f["Period"].map(dict(zip(dim_period.Period, dim_period.Sort)))
    prev_key = ["LEI_Code", "ItemKey", "ASSETS_FV", "ASSETS_Stages", "Exposure",
                "Financial_instruments"]
    p = f[pl].sort_values(prev_key + ["PeriodSort"]).copy()
    grp = p.groupby(prev_key, sort=False)
    p["prev_amount"] = grp["Amount"].shift(1)
    p["prev_nq"] = grp["n_quarters"].shift(1)
    p["prev_sort"] = grp["PeriodSort"].shift(1)
    first_q = p["n_quarters"] == 1
    chained = (p["prev_sort"] == p["PeriodSort"] - 1) & (p["prev_nq"] == p["n_quarters"] - 1)
    p["Quarterly"] = np.where(first_q, p["Amount"],
                              np.where(chained, p["Amount"] - p["prev_amount"], np.nan))
    f["Quarterly"] = np.nan
    f.loc[p.index, "Quarterly"] = p["Quarterly"]
    # Stocks (balance sheet, capital, RWA) are point-in-time; their quarterly value is the value.
    f.loc[~pl, "Quarterly"] = f.loc[~pl, "Amount"]
    q["pl_rows"] = int(pl.sum())
    q["pl_rows_not_decumulable"] = int(p["Quarterly"].isna().sum())
    q["pl_not_decumulable_periods"] = p.loc[p["Quarterly"].isna(), "Period"].value_counts() \
        .sort_index().to_dict()

    # ------------------------------------------------------------------ items
    latest = f.sort_values("Exercise").drop_duplicates("ItemKey", keep="last")
    it = latest[["ItemKey", "Label", "Sheet"]].copy()
    it["Label"] = it["Label"].str.replace(" ", " ").str.replace(r"\s+", " ", regex=True) \
        .str.strip()
    # Whole-word match: a substring test for "ratio" finds it inside "Operational" and
    # "operations", and flags operational-risk RWAs and profit from continuing operations.
    it["IsRatio"] = np.where(it["Label"].str.contains(r"\bratio\b", case=False) &
                             ~it["Label"].str.contains("exposure|numerator", case=False) &
                             (it["Sheet"] != "P&L"), "Yes", "No")
    it["RwaComponent"] = it["ItemKey"].map(lambda k: RWA_COMPONENTS.get(k, ("", 0))[0])
    it["RwaSort"] = it["ItemKey"].map(lambda k: RWA_COMPONENTS.get(k, ("", 0))[1])
    it["Basis"] = np.where(it["Sheet"] == "P&L", "Year to date",
                           np.where(it["IsRatio"] == "Yes", "Ratio", "Point in time"))
    it = it.rename(columns={"Sheet": "Template"})
    it["ItemSort"] = it["ItemKey"].astype(int)
    q["items"] = int(len(it))
    q["items_by_template"] = it.groupby("Template").size().to_dict()
    q["ratio_items"] = int((it.IsRatio == "Yes").sum())

    stage = pd.DataFrame({"StageKey": [0, 1, 2, 3],
                          "Stage": ["Not staged", "Stage 1", "Stage 2", "Stage 3"],
                          "StageMeaning": ["", "Performing", "Significant increase in credit risk",
                                           "Credit-impaired"]})

    # ------------------------------------------------------------------ fact
    fact = f[["LEI_Code", "Period", "ItemKey", "ASSETS_Stages", "n_quarters", "Amount",
              "Quarterly"]].rename(
        columns={"LEI_Code": "LEI", "ASSETS_Stages": "StageKey", "n_quarters": "QuartersInYTD"})
    fact["Amount"] = fact["Amount"].round(6)
    fact["Quarterly"] = fact["Quarterly"].round(6)
    fact = fact.sort_values(["Period", "LEI", "ItemKey"]).reset_index(drop=True)

    # ------------------------------------------------------------------ checks worth recording
    cap = fact[fact.ItemKey.isin(["2520102", "2520138", "2520140"]) & (fact.StageKey == 0)]
    w = cap.pivot_table(index=["LEI", "Period"], columns="ItemKey", values="Amount")
    w = w.dropna()
    q["cet1_ratio_reported_vs_computed_max_diff"] = float(
        (w["2520102"] / w["2520138"] - w["2520140"]).abs().max())
    last = ps[-1]
    wl = w.xs(last, level="Period")
    q["cet1_latest"] = {"period": last,
                        "aggregate_ratio": round(float(wl["2520102"].sum() / wl["2520138"].sum()), 6),
                        "simple_average_of_ratios": round(float(wl["2520140"].mean()), 6),
                        "median": round(float(wl["2520140"].median()), 6),
                        "banks": int(len(wl))}

    rwa = fact[fact.ItemKey.isin(list(RWA_COMPONENTS))].groupby(["LEI", "Period"])["Amount"].sum()
    trea = fact[fact.ItemKey == "2520138"].set_index(["LEI", "Period"])["Amount"]
    gap = (rwa - trea).abs().dropna()
    q["rwa_components_vs_total_max_gap"] = round(float(gap.max()), 3)
    q["rwa_components_vs_total_gaps_over_1m"] = int((gap > 1).sum())

    print("data/")
    write_csv(dim_bank, "dim_bank.csv")
    write_csv(dim_period, "dim_period.csv")
    write_csv(it.sort_values("ItemSort"), "dim_item.csv")
    write_csv(stage, "dim_stage.csv")
    for y in YEARS:
        per = dim_period.loc[dim_period.Exercise == y, "Period"]
        write_csv(fact[fact.Period.isin(per)], f"fact_prudential_{y}.csv")

    (DATA / "quality_report.json").write_text(json.dumps(q, indent=2, default=str) + LF,
                                              encoding="utf-8", newline=LF)
    print("\ndata/quality_report.json")
    for k in ("aggregate_rows_dropped", "breakdown_rows_dropped", "banks",
              "banks_in_all_three", "banks_in_constant_panel", "banks_by_size_band",
              "non_calendar_year_banks", "items", "items_by_template", "ratio_items",
              "pl_rows_not_decumulable", "pl_not_decumulable_periods",
              "cet1_ratio_reported_vs_computed_max_diff", "rwa_components_vs_total_max_gap",
              "rwa_components_vs_total_gaps_over_1m", "cet1_latest"):
        print("  %-42s %s" % (k, q[k]))


if __name__ == "__main__":
    main()
