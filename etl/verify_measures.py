"""Recompute the headline measures in pandas and diff them against what the model returns.

The model is the thing being checked, so the check cannot use it. This reads data/ straight
from the CSVs and recomputes capital, ratios, asset quality and profit by quarter, by size band
and by year, then compares them to the CSV that etl/checks/verify.dax produced against the live
model.

    powershell -File etl/query_model.ps1 -DaxFile etl/checks/verify.dax -Csv > etl/checks/dax_actual.csv
    python etl/verify_measures.py

Non-zero exit means a measure and its pandas equivalent disagree.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ACTUAL = ROOT / "etl" / "checks" / "dax_actual.csv"

CET1, TREA, T1_LEV, LEV_EXP, LOANS, PROFIT = 2520102, 2520138, 2520901, 2520903, 2521019, 2520335
FIELDS = ["cet1", "trea", "ratio", "avg", "median", "banks", "leverage", "stage3", "panel",
          "profit", "profit_naive"]
TOL = {"cet1": 0.01, "trea": 0.01, "profit": 0.01, "profit_naive": 0.01, "banks": 0.5}


def load():
    f = pd.concat([pd.read_csv(p, dtype={"LEI": str}) for p in sorted(DATA.glob("fact_*.csv"))],
                  ignore_index=True)
    per = pd.read_csv(DATA / "dim_period.csv")
    bank = pd.read_csv(DATA / "dim_bank.csv", dtype={"LEI": str})
    f = f.merge(per[["Period", "Label", "Year", "Quarter", "Sort"]], on="Period") \
         .merge(bank[["LEI", "SizeBand", "InConstantPanel"]], on="LEI")
    return f, per


def at(f: pd.DataFrame, sort: int, item: int) -> pd.Series:
    """One item at one quarter, per bank."""
    x = f[(f.Sort == sort) & (f.ItemKey == item)]
    return x.groupby("LEI")["Amount"].sum()


def capital(f: pd.DataFrame, sort: int) -> dict:
    c, t = at(f, sort, CET1), at(f, sort, TREA)
    per_bank = (c / t).dropna()
    loans = f[(f.Sort == sort) & (f.ItemKey == LOANS)]
    panel = f[f.InConstantPanel == "Yes"]
    pc, pt = at(panel, sort, CET1), at(panel, sort, TREA)
    return dict(
        cet1=round(c.sum(), 3), trea=round(t.sum(), 3),
        ratio=round(c.sum() / t.sum(), 8) if t.sum() else 0.0,
        avg=round(per_bank.mean(), 8), median=round(per_bank.median(), 8),
        banks=int(c.index.nunique()),
        leverage=round(at(f, sort, T1_LEV).sum() / at(f, sort, LEV_EXP).sum(), 8),
        stage3=round(loans.loc[loans.StageKey == 3, "Amount"].sum() / loans.Amount.sum(), 8)
        if len(loans) else 0.0,
        panel=round(pc.sum() / pt.sum(), 8) if pt.sum() else 0.0,
    )


def full_year(f: pd.DataFrame, year: int) -> float:
    x = f[(f.ItemKey == PROFIT) & (f.QuartersInYTD == 4) & (f.Year == year)]
    return round(float(x.Amount.sum()), 3)


def main() -> None:
    if not ACTUAL.exists():
        print(f"missing {ACTUAL} - run query_model.ps1 against the live model first")
        sys.exit(2)
    actual = pd.read_csv(ACTUAL)
    actual.columns = [c.strip("[]") for c in actual.columns]
    actual["key"] = actual["key"].astype(str)

    f, per = load()
    last = int(per.Sort.max())
    complete = sorted(per.loc[per.Quarter == 4, "Year"].unique())
    rows = []
    for r in per.itertuples():
        q = f[f.Sort == r.Sort]
        rows.append(dict(grain="quarter", key=r.Label, **capital(f, r.Sort),
                         profit=round(float(q.loc[q.ItemKey == PROFIT, "Quarterly"].sum()), 3),
                         profit_naive=float("nan")))
    for band, g in f.groupby("SizeBand"):
        rows.append(dict(grain="size", key=band, **capital(g, last),
                         profit=full_year(g, complete[-1]), profit_naive=float("nan")))
    for y in sorted(per.Year.unique()):
        fy = full_year(f, y) if y in complete else float("nan")
        naive = round(float(f[(f.ItemKey == PROFIT) & (f.Year == y)].Amount.sum()), 3) \
            if y in complete else float("nan")
        rows.append(dict(grain="year", key=str(y), profit=fy, profit_naive=naive))
    expected = pd.DataFrame(rows)
    # SUMMARIZECOLUMNS drops a group whose measures are all blank - 2025, which has no complete
    # financial year - so an all-blank expected row has nothing to match, and that is agreement.
    expected = expected[expected[FIELDS].notna().any(axis=1)]

    merged = expected.merge(actual, on=["grain", "key"], how="outer",
                            suffixes=("_pandas", "_dax"), indicator="side")
    problems = [f"{r.grain}/{r.key}: present in {r.side} only"
                for r in merged[merged["side"] != "both"].itertuples()]
    both = merged[merged["side"] == "both"]
    checks = 0
    for field in FIELDS:
        a = both[f"{field}_pandas"].astype(float)
        b = both[f"{field}_dax"].astype(float)
        # Both blank is agreement. One blank and one not is a mismatch - DAX BLANK is NaN here,
        # and NaN > tol is False, so it has to be tested for explicitly rather than let through.
        either = a.notna() | b.notna()
        diff = (a.fillna(0.0) - b.fillna(0.0)).abs()
        bad = either & ((a.isna() != b.isna()) | (diff > TOL.get(field, 1e-6)))
        checks += int(either.sum())
        for r, av, bv in zip(both[bad].itertuples(), a[bad], b[bad]):
            problems.append(f"{r.grain}/{r.key} {field}: pandas={av} dax={bv}")

    print(f"{len(both)} rows compared, {checks} checks")
    if problems:
        print("\nMISMATCHES")
        for p in problems:
            print("  " + p)
        sys.exit(1)
    print("every figure agrees")

    latest = expected[(expected.grain == "quarter")].iloc[-1]
    print(f"\nheadline at {latest.key}, recomputed from the CSVs:")
    # Subscripts, not attributes: latest.median is the Series method, not the column.
    print(f"  banks                    {int(latest['banks'])}")
    print(f"  CET1 ratio, sector       {latest['ratio']:.2%}")
    print(f"  CET1, average of banks   {latest['avg']:.2%}  "
          f"(+{(latest['avg'] - latest['ratio']) * 100:.1f} pts)")
    print(f"  CET1, median bank        {latest['median']:.2%}")
    print(f"  leverage ratio           {latest['leverage']:.2%}")
    print(f"  stage 3 ratio            {latest['stage3']:.2%}")
    for r in expected[(expected.grain == "year") & expected.profit.notna()].itertuples():
        print(f"  FY{r.key} profit €{r.profit / 1000:,.1f}bn; four YTD figures added "
              f"€{r.profit_naive / 1000:,.1f}bn ({r.profit_naive / r.profit:.2f}x)")


if __name__ == "__main__":
    main()
