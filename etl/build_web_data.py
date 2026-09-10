"""Emit the JSON the milestonebi.com case study reads.

The case study redraws the Power BI report for the web, so its numbers have to be the same
numbers. They are computed here from data/ - the same CSVs the model loads - rather than typed
into the page, and verify_measures.py has already proved that those CSVs and the model agree.

    python etl/build_web_data.py [--out <path>]

Writes web/bank-capital.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "web" / "bank-capital.json"

CET1, TREA, T1_LEV, LEV_EXP, ASSETS, LOANS, PROFIT = (
    2520102, 2520138, 2520901, 2520903, 2521010, 2521019, 2520335)


def r(v, dp=2):
    return None if pd.isna(v) else round(float(v), dp)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    f = pd.concat([pd.read_csv(p, dtype={"LEI": str}) for p in sorted(DATA.glob("fact_*.csv"))],
                  ignore_index=True)
    per = pd.read_csv(DATA / "dim_period.csv")
    bank = pd.read_csv(DATA / "dim_bank.csv", dtype={"LEI": str})
    item = pd.read_csv(DATA / "dim_item.csv")
    quality = json.loads((DATA / "quality_report.json").read_text(encoding="utf-8"))
    f = f.merge(per[["Period", "Label", "Year", "Quarter", "Sort"]], on="Period") \
         .merge(bank[["LEI", "SizeBand", "SizeBandSort", "InConstantPanel"]], on="LEI")
    last = int(per.Sort.max())
    panel = f[f.InConstantPanel == "Yes"]

    def wide(g: pd.DataFrame, sort: int) -> pd.DataFrame:
        x = g[(g.Sort == sort) & g.ItemKey.isin([CET1, TREA, T1_LEV, LEV_EXP, ASSETS])]
        return x.pivot_table(index="LEI", columns="ItemKey", values="Amount", aggfunc="sum")

    out: dict = {}

    q = []
    for p in per.itertuples():
        w = wide(panel, p.Sort).dropna(subset=[CET1, TREA])
        ratios = w[CET1] / w[TREA]
        loans = panel[(panel.Sort == p.Sort) & (panel.ItemKey == LOANS)]
        q.append(dict(
            quarter=p.Label, banks=int(len(w)),
            aggregate=r(w[CET1].sum() / w[TREA].sum(), 5), average=r(ratios.mean(), 5),
            median=r(ratios.median(), 5),
            stage2=r(loans.loc[loans.StageKey == 2, "Amount"].sum() / loans.Amount.sum(), 5),
            stage3=r(loans.loc[loans.StageKey == 3, "Amount"].sum() / loans.Amount.sum(), 5),
        ))
    out["panel_by_quarter"] = q

    w = wide(f, last).dropna(subset=[CET1, TREA])
    w = w.join(bank.set_index("LEI")[["Bank", "SizeBand", "SizeBandSort", "CountryCode"]])
    w["ratio"] = w[CET1] / w[TREA]
    out["banks_latest"] = [
        dict(bank=b.Bank, country=b.CountryCode, band=b.SizeBand, ratio=r(b.ratio, 4),
             rwa=r(b[TREA] / 1000, 1), assets=r(b[ASSETS] / 1000, 1))
        for _, b in w.sort_values(TREA, ascending=False).iterrows()]
    bands = []
    for (band, s), g in w.groupby(["SizeBand", "SizeBandSort"]):
        bands.append(dict(band=band, sort=int(s), banks=int(len(g)),
                          aggregate=r(g[CET1].sum() / g[TREA].sum(), 4),
                          average=r(g.ratio.mean(), 4),
                          rwa_share=r(g[TREA].sum() / w[TREA].sum(), 4),
                          density=r(g[TREA].sum() / g[ASSETS].sum(), 4)))
    out["by_size"] = sorted(bands, key=lambda d: d["sort"])

    comp = item[item.RwaComponent.notna() & (item.RwaComponent != "")]
    mix = f[(f.Sort == last) & f.ItemKey.isin(comp.ItemKey)] \
        .merge(comp[["ItemKey", "RwaComponent", "RwaSort"]], on="ItemKey") \
        .groupby(["RwaComponent", "RwaSort"]).Amount.sum().reset_index().sort_values("RwaSort")
    out["rwa_mix"] = [dict(component=c, amount_bn=r(a / 1000, 1))
                      for c, a in zip(mix.RwaComponent, mix.Amount)]

    complete = sorted(per.loc[per.Quarter == 4, "Year"].unique())
    years = []
    for y in complete:
        p = f[(f.ItemKey == PROFIT) & (f.Year == y)]
        fy = p.loc[p.QuartersInYTD == 4, "Amount"].sum()
        years.append(dict(year=int(y), profit_bn=r(fy / 1000, 1),
                          naive_bn=r(p.Amount.sum() / 1000, 1), ratio=r(p.Amount.sum() / fy, 2)))
    out["profit_by_year"] = years

    agg = w[CET1].sum() / w[TREA].sum()
    out["totals"] = dict(
        quarter=per.loc[per.Sort == last, "Label"].iloc[0], banks=int(len(w)),
        banks_all=int(len(bank)), panel=int((bank.InConstantPanel == "Yes").sum()),
        countries=int(bank.CountryCode.nunique()),
        aggregate=r(agg, 4), average=r(w.ratio.mean(), 4), median=r(w.ratio.median(), 4),
        leverage=r(w[T1_LEV].sum() / w[LEV_EXP].sum(), 4),
        cet1_bn=r(w[CET1].sum() / 1000, 0), rwa_bn=r(w[TREA].sum() / 1000, 0),
        assets_bn=r(w[ASSETS].sum() / 1000, 0),
        above_aggregate=int((w.ratio > agg).sum()),
    )
    out["quality"] = {k: quality[k] for k in (
        "aggregate_rows_dropped", "breakdown_rows_dropped", "banks", "banks_in_all_three",
        "banks_in_constant_panel", "non_calendar_year_banks", "items", "items_by_template",
        "pl_rows", "pl_rows_not_decumulable", "cet1_ratio_reported_vs_computed_max_diff",
        "rwa_components_vs_total_max_gap", "key_metrics_rows_dropped_2023",
        "key_metrics_rows_dropped_2025",
    )}

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")
    print(f"{path} {path.stat().st_size / 1024:.1f} KB")
    t = out["totals"]
    print(f"  {t['quarter']}: {t['banks']} banks, CET1 sector {t['aggregate']:.2%}, "
          f"average {t['average']:.2%}, median {t['median']:.2%}; "
          f"{t['above_aggregate']} banks above the sector ratio")
    for y in years:
        print(f"  FY{y['year']} profit €{y['profit_bn']}bn, YTD added €{y['naive_bn']}bn "
              f"({y['ratio']}x)")


if __name__ == "__main__":
    main()
