"""Flujos netos (aportes - rescates) de fondos mutuos por tipo de fondo, datos CMF.

Fuente: CMF, "Consulta de Patrimonio, Rentabilidad, Partícipes y Valor de la Cuota
de Fondos Mutuos" (consulta mensual por fecha, todas las administradoras):
    https://www.cmfchile.cl/institucional/estadisticas/fm.bpr_menu.php
endpoint de descarga: fm.fm_bpr.php (Excel). Cada mes trae una fila por tipo de
fondo (Tipo 1..8) y el total del sistema, con patrimonio en millones de pesos
corrientes, rentabilidad nominal mensual (%) y número de partícipes.

La CMF no publica aportes y rescates agregados por tipo sin captcha (la cartola
diaria por fondo lo exige), así que el flujo neto se obtiene de forma implícita:

    flujo_t = patrimonio_t - patrimonio_{t-1} * (1 + rentabilidad_t)

es decir, la variación de patrimonio que no se explica por la rentabilidad del
mes. Positivo = entradas netas (aportes > rescates).

Uso:
    python analysis/flujos_fondos_mutuos.py               # 2010-01 .. último mes
    python analysis/flujos_fondos_mutuos.py --desde 2000-01 --hasta 2026-09
"""

from __future__ import annotations

import argparse
import io
import time
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

URL = (
    "https://www.cmfchile.cl/institucional/estadisticas/fm.fm_bpr.php"
    "?admins=0&tipofondo=0&moneda=0&mes_peri={mes:02d}&anio_peri={anio}"
    "&out=excel&lang=es"
)

TIPOS = {
    1: "Tipo 1 - Deuda CP <= 90 días",
    2: "Tipo 2 - Deuda CP <= 365 días",
    3: "Tipo 3 - Deuda mediano y largo plazo",
    4: "Tipo 4 - Mixto",
    5: "Tipo 5 - Capitalización",
    6: "Tipo 6 - Libre inversión",
    7: "Tipo 7 - Estructurado",
    8: "Tipo 8 - Inversionistas calificados",
    0: "Total sistema",
}

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache" / "cmf_fm_bpr"
OUT = HERE / "outputs"


def descargar_mes(anio: int, mes: int, refrescar: bool = False) -> bytes:
    """Descarga (o lee del caché) el Excel mensual de la CMF."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"fm_bpr_{anio}{mes:02d}.xls"
    if f.exists() and not refrescar:
        return f.read_bytes()
    req = urllib.request.Request(
        URL.format(anio=anio, mes=mes), headers={"User-Agent": "Mozilla/5.0"}
    )
    for intento in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            break
        except Exception:
            if intento == 3:
                raise
            time.sleep(2 ** (intento + 1))
    f.write_bytes(data)
    time.sleep(0.5)  # no saturar el sitio de la CMF
    return data


def parsear_mes(data: bytes, anio: int, mes: int) -> pd.DataFrame:
    """Extrae las filas 'FM Tipo N' y 'Total Sistema' del Excel de la CMF."""
    raw = pd.read_excel(io.BytesIO(data), header=None, engine="xlrd")
    etiqueta = raw[0].astype(str).str.strip()
    filas = raw[etiqueta.str.match(r"^(FM Tipo \d|Total Sistema)$")]
    if filas.empty:
        return pd.DataFrame()
    out = pd.DataFrame(
        {
            "fecha": pd.Timestamp(anio, mes, 1) + pd.offsets.MonthEnd(0),
            "tipo": [
                0 if e.startswith("Total") else int(e.split()[-1])
                for e in filas[0].astype(str).str.strip()
            ],
            # columnas del informe: 6 patrimonio (MM$), 9 rentabilidad nominal (%),
            # 10 partícipes
            "patrimonio_mm": pd.to_numeric(filas[6], errors="coerce").values,
            "rent_nominal_pct": pd.to_numeric(filas[9], errors="coerce").values,
            "participes": pd.to_numeric(filas[10], errors="coerce").values,
        }
    )
    return out


def meses(desde: str, hasta: str):
    for p in pd.period_range(desde, hasta, freq="M"):
        yield p.year, p.month


def construir_panel(desde: str, hasta: str, refrescar: bool = False) -> pd.DataFrame:
    partes = []
    for anio, mes in meses(desde, hasta):
        try:
            df = parsear_mes(descargar_mes(anio, mes, refrescar), anio, mes)
        except Exception as e:  # mes sin datos / error puntual
            print(f"  {anio}-{mes:02d}: error {e}")
            continue
        if df.empty:
            print(f"  {anio}-{mes:02d}: sin datos")
            continue
        partes.append(df)
    panel = pd.concat(partes, ignore_index=True)
    panel["nombre_tipo"] = panel["tipo"].map(TIPOS)
    return panel.sort_values(["tipo", "fecha"]).reset_index(drop=True)


def calcular_flujos(panel: pd.DataFrame) -> pd.DataFrame:
    p = panel.copy()
    g = p.groupby("tipo")
    p["patrimonio_mm_ant"] = g["patrimonio_mm"].shift(1)
    # sólo meses consecutivos
    consecutivo = g["fecha"].diff().dt.days.between(27, 32)
    p.loc[~consecutivo, "patrimonio_mm_ant"] = pd.NA
    p["efecto_rentabilidad_mm"] = p["patrimonio_mm_ant"] * p["rent_nominal_pct"] / 100
    p["flujo_neto_mm"] = (
        p["patrimonio_mm"] - p["patrimonio_mm_ant"] - p["efecto_rentabilidad_mm"]
    )
    p["flujo_neto_pct_patrimonio"] = 100 * p["flujo_neto_mm"] / p["patrimonio_mm_ant"]
    p["variacion_participes"] = g["participes"].diff()
    cols = [
        "fecha", "tipo", "nombre_tipo", "patrimonio_mm", "rent_nominal_pct",
        "participes", "efecto_rentabilidad_mm", "flujo_neto_mm",
        "flujo_neto_pct_patrimonio", "variacion_participes",
    ]
    return p[cols]


def main() -> None:
    hoy = date.today()
    ultimo = (pd.Timestamp(hoy) - pd.offsets.MonthBegin(1) - pd.DateOffset(months=1))
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="2010-01")
    ap.add_argument("--hasta", default=ultimo.strftime("%Y-%m"))
    ap.add_argument("--refrescar", action="store_true", help="ignorar caché")
    a = ap.parse_args()

    print(f"Descargando CMF fondos mutuos {a.desde} .. {a.hasta}")
    panel = construir_panel(a.desde, a.hasta, a.refrescar)
    flujos = calcular_flujos(panel)

    OUT.mkdir(parents=True, exist_ok=True)
    flujos.to_csv(OUT / "flujos_fondos_mutuos_por_tipo_long.csv", index=False)

    ancho = flujos.pivot(index="fecha", columns="nombre_tipo", values="flujo_neto_mm")
    ancho = ancho[[TIPOS[k] for k in TIPOS if TIPOS[k] in ancho.columns]]
    ancho.to_csv(OUT / "flujos_fondos_mutuos_por_tipo_mensual.csv")

    anual = ancho.groupby(ancho.index.year).sum(min_count=1)
    anual.index.name = "anio"
    anual.to_csv(OUT / "flujos_fondos_mutuos_por_tipo_anual.csv")

    pd.set_option("display.width", 250)
    print("\nFlujo neto anual por tipo (millones de $ corrientes):")
    print((anual / 1).round(0).to_string())

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        # suma móvil 12m en billones de $ (10^12); Tipo 1 (money market) va en un
        # panel aparte porque su estacionalidad de fin de mes domina la escala
        m = (ancho / 1e6).rolling(12, min_periods=12).sum()
        resto = [TIPOS[k] for k in range(2, 9) if TIPOS[k] in m.columns]
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
        m[[TIPOS[1], TIPOS[0]]].plot(ax=ax1, lw=1.6, color=["tab:blue", "k"])
        m[resto].plot(ax=ax2, lw=1.4)
        for ax in (ax1, ax2):
            ax.axhline(0, color="k", lw=0.6)
            ax.set_ylabel("Billones de $ (10^12)")
            ax.set_xlabel("")
            ax.legend(fontsize=8, ncol=2, loc="upper left")
            ax.grid(alpha=0.3)
        ax1.set_title(
            "Fondos mutuos Chile — flujo neto implícito por tipo (suma móvil 12 meses)"
        )
        fig.tight_layout()
        fig.savefig(OUT / "flujos_fondos_mutuos_por_tipo.png", dpi=130)
    except ImportError:
        pass


if __name__ == "__main__":
    main()
