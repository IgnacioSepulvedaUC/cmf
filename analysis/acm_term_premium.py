"""ACM term premium for Chilean CMF curves — sovereign, bank and corporate.

Estimates the Adrian-Crump-Moench (ACM) nominal term-premium decomposition for
three segments of the Chilean fixed-income market and reports the premium at the
longest available maturity (30 years / 10,800 days), as requested.

Segments (highest rating available, one representative curve per segment):
    - Soberano    : "Gob CERO Pesos"      (nominal zero-coupon sovereign curve)
    - Bancario    : "CORP Bancarios AAA"  (AAA bank-bond curve)
    - Corporativo : "CORP AAA"            (AAA corporate curve)

Method
------
The ACM estimator is taken from the `nachometrics` package
(nachometrics.nachoquant.nachorates.premiums.ACM). The workflow:

    1. Pick one quote per trading day (official 13:45 close when available,
       else the 09:40 quote).
    2. Resample to month-end (ACM is classically estimated on monthly data;
       the risk-neutral iteration is also intractable at daily frequency).
    3. Build a zero-yield panel on the tenor grid below, converting rates from
       percent to annual decimals and days to years (days / 360).
    4. Fit ACM with 3 PCA factors (level/slope/curvature). Five factors — the
       textbook ACM default — makes the Q-measure VAR explosive on this short
       (~127-month) sample and blows up the long end; three factors keep the
       risk-neutral dynamics non-explosive while still explaining 98-99.9% of
       curve variation.

Outputs (written to ./outputs):
    - term_premium_acm_30y.csv       : monthly 30y term-premium series, 3 curves
    - term_premium_acm_full.csv      : full term-premium panel (all tenors)
    - term_premium_acm_summary.csv   : latest value + sample stats per curve
    - term_premium_acm_30y.png       : chart of the three 30y series

Set NACHOMETRICS_PATH to the unpacked `nachometrics_unified_*` directory, or
place it next to this script.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUTDIR = HERE / "outputs"
OUTDIR.mkdir(exist_ok=True)

# Locate the nachometrics package (provides the ACM estimator).
_nacho_path = os.environ.get("NACHOMETRICS_PATH")
if _nacho_path:
    sys.path.insert(0, _nacho_path)
else:
    for candidate in HERE.glob("nachometrics_unified_*"):
        if (candidate / "nachometrics").is_dir():
            sys.path.insert(0, str(candidate))
            break

from nachometrics.nachoquant.nachorates.premiums import ACM  # noqa: E402

# --- Configuration ----------------------------------------------------------
CURVE_PARQUET = os.environ.get(
    "CURVE_PARQUET",
    "/root/.claude/uploads/9d704e09-1b3a-56e9-b9c5-10597ad000eb/a15596e8-curva.parquet",
)

# Tenor grid in days (30 days .. 30 years). 10800 days = 30y is "la mas larga".
PLAZOS = [90, 180, 360, 720, 1080, 1800, 2520, 3600, 5400, 7200, 9000, 10800]
DAYS_PER_YEAR = 360.0
MATURITIES = [round(p / DAYS_PER_YEAR, 6) for p in PLAZOS]
SHORT_TENOR = round(90 / DAYS_PER_YEAR, 6)   # 3-month short rate
LONGEST = MATURITIES[-1]                       # 30y
N_FACTORS = 3
FREQUENCY = "monthly"

# One representative curve per segment (highest rating available).
SEGMENTS = {
    "Soberano": "Gob CERO Pesos",
    "Bancario": "CORP Bancarios AAA",
    "Corporativo": "CORP AAA",
}

# Prefer the official 13:45 close, then 09:40, then the single-tenor quote.
HORA_PRIORITY = {"13:45 (Oficial)": 0, "09:40": 1, "Plazo único": 2}


def load_raw() -> pd.DataFrame:
    df = pd.read_parquet(CURVE_PARQUET)
    df["fecha_dt"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y")
    df["prio"] = df["hora"].map(HORA_PRIORITY).fillna(9)
    return df


def monthly_long(df: pd.DataFrame, curva: str) -> pd.DataFrame:
    """Return the canonical long zero-yield panel (date, tenor, rate) for a curve."""
    sub = df[(df["curva"] == curva) & (df["plazo_dias"].isin(PLAZOS))].copy()
    sub = sub.sort_values(["fecha_dt", "plazo_dias", "prio"])
    sub = sub.drop_duplicates(["fecha_dt", "plazo_dias"], keep="first")
    wide = sub.pivot(index="fecha_dt", columns="plazo_dias", values="valor")
    wide = wide.resample("ME").last().dropna()
    rows = [
        (dt, round(p / DAYS_PER_YEAR, 6), row[p] / 100.0)  # percent -> decimal
        for dt, row in wide.iterrows()
        for p in PLAZOS
    ]
    return pd.DataFrame(rows, columns=["date", "tenor", "rate"])


def main() -> None:
    df = load_raw()
    tp30 = {}
    full_frames = []
    summary_rows = []

    for segment, curva in SEGMENTS.items():
        long = monthly_long(df, curva)
        res = ACM(
            long,
            maturities=MATURITIES,
            n_factors=N_FACTORS,
            short_rate_tenor=SHORT_TENOR,
            frequency=FREQUENCY,
        ).fit()

        tp = res.term_premium()          # decimal, index=date, columns=tenor
        diag = res.diagnostics()
        s30 = tp[LONGEST] * 100.0        # percentage points
        tp30[f"{segment} ({curva})"] = s30

        panel = tp.copy() * 100.0
        panel.insert(0, "curva", curva)
        panel.insert(0, "segmento", segment)
        full_frames.append(panel)

        summary_rows.append(
            {
                "segmento": segment,
                "curva": curva,
                "obs_mensuales": int(diag["n_obs"]),
                "muestra_inicio": tp.index.min().date().isoformat(),
                "muestra_fin": tp.index.max().date().isoformat(),
                "tenor_anios": LONGEST,
                "tp30_ultimo_pp": round(float(s30.iloc[-1]), 3),
                "tp30_ultimo_bps": round(float(s30.iloc[-1]) * 100, 1),
                "tp30_media_pp": round(float(s30.mean()), 3),
                "tp30_min_pp": round(float(s30.min()), 3),
                "tp30_max_pp": round(float(s30.max()), 3),
                "var_explicada": round(float(diag["explained_variance_total"]), 5),
                "eig_max_Q": round(float(diag["state_max_abs_eigenvalue_q"]), 4),
                "rmse_precio_bps": round(float(diag["pricing_error_rmse"]) * 1e4, 2),
            }
        )
        print(
            f"{segment:12s} {curva:20s} obs={diag['n_obs']:3d} "
            f"tp30 last={s30.iloc[-1]:+.2f}pp mean={s30.mean():+.2f}pp "
            f"eigQ={diag['state_max_abs_eigenvalue_q']:.4f}"
        )

    # 30y term-premium time series (three curves).
    tp30_df = pd.DataFrame(tp30)
    tp30_df.index.name = "date"
    tp30_df.to_csv(OUTDIR / "term_premium_acm_30y.csv", float_format="%.4f")

    pd.concat(full_frames).to_csv(OUTDIR / "term_premium_acm_full.csv", float_format="%.4f")

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(OUTDIR / "term_premium_acm_summary.csv", index=False)
    print("\nSummary (30y term premium):")
    print(summary.to_string(index=False))

    # Chart.
    fig, ax = plt.subplots(figsize=(10, 5.5))
    colors = ["#2563eb", "#16a34a", "#dc2626"]
    for (name, series), color in zip(tp30_df.items(), colors):
        ax.plot(tp30_df.index, series, label=name, color=color, linewidth=1.8)
    ax.axhline(0.0, color="#6b7280", linewidth=0.8, linestyle="--")
    ax.set_title("ACM term premium — 30-year (longest) tenor\nChilean CMF curves, monthly")
    ax.set_ylabel("Term premium (percentage points)")
    ax.set_xlabel("")
    ax.legend(frameon=False, fontsize=9)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUTDIR / "term_premium_acm_30y.png", dpi=140)
    print(f"\nWrote outputs to {OUTDIR}")


if __name__ == "__main__":
    main()
