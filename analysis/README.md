# Term premium ACM — soberanos, bancarios y corporativos

Descomposición de term premium tipo **Adrian-Crump-Moench (ACM)** para tres
segmentos de la curva chilena (datos CMF, `curva.parquet`), reportando el premio
en el **plazo más largo disponible: 30 años (10.800 días)**.

## Curvas usadas (una representativa por segmento, mejor clasificación)

| Segmento | Curva | Tipo |
|---|---|---|
| Soberano | `Gob CERO Pesos` | cupón cero soberano nominal |
| Bancario | `CORP Bancarios AAA` | bonos bancarios AAA |
| Corporativo | `CORP AAA` | bonos corporativos AAA |

El método es idéntico para cualquier otra clasificación (AA, A, BBB), curva UF
(`Gob CERO UF`, `CORP UF ...`) o TIR (`Gob TIR BCP`): basta cambiar el nombre en
`SEGMENTS` dentro de `acm_term_premium.py`.

## Metodología

1. **Una cotización por día**: se prefiere el cierre oficial `13:45 (Oficial)`;
   si no existe, `09:40`; luego `Plazo único`.
2. **Frecuencia mensual** (fin de mes). ACM se estima clásicamente en datos
   mensuales; además la iteración riesgo-neutral es intratable en frecuencia
   diaria (30 años × 252 pasos × ~2.600 fechas).
3. **Panel de tasas cero** sobre la grilla 90d…10.800d, convirtiendo de porcentaje
   a decimal anual y de días a años (días / 360).
4. **ACM con 3 factores PCA** (nivel/pendiente/curvatura). Con 5 factores —el
   default de ACM— la VAR bajo la medida Q se vuelve explosiva en esta muestra
   corta (~127 meses) y el tramo largo diverge; 3 factores mantienen la dinámica
   riesgo-neutral no explosiva y explican 98–99,9% de la variación de la curva.
   Tasa corta = 3 meses (90 días).

Estimador: `nachometrics.nachoquant.nachorates.premiums.ACM` (paquete
`nachometrics_unified`).

## Resultado — term premium a 30 años (último dato, 2026-07-31)

| Segmento | Term premium 30a | Media muestral | Rango (min…max) |
|---|---|---|---|
| Soberano (Gob CERO Pesos) | **−1,01 pp** (−101 bps) | −1,11 pp | −1,30 … −0,93 |
| Bancario (CORP Bancarios AAA) | **−2,61 pp** (−261 bps) | −2,56 pp | −2,89 … −2,18 |
| Corporativo (CORP AAA) | **−1,12 pp** (−112 bps) | −1,38 pp | −2,24 … −0,71 |

Muestra: mensual, ene-2016 a jul-2026 (soberano y bancario 127 meses; corporativo
99 meses por meses incompletos entre ~2019–2021, visible como corte en el gráfico).

**Lectura.** El term premium a 30 años es **negativo** en los tres segmentos: la
trayectoria esperada de tasas cortas que implica la VAR bajo la medida física se
ubica por encima de la tasa larga observada, de modo que el tramo largo cotiza con
premio negativo. Es un rasgo conocido de estas descomposiciones en muestras cortas
y con curvas largas planas/invertidas; el nivel (no tanto el signo) es sensible al
número de factores y al largo de muestra. El premio bancario AAA es el más negativo
(≈ −2,6 pp), y el soberano el menos negativo (≈ −1,0 pp).

## Reproducir

```bash
pip install numpy pandas pyarrow scipy statsmodels scikit-learn joblib networkx matplotlib
export NACHOMETRICS_PATH=/ruta/a/nachometrics_unified_v0.7.0_final
export CURVE_PARQUET=/ruta/a/curva.parquet   # opcional
python3 acm_term_premium.py
```

## Salidas (`outputs/`)

- `term_premium_acm_30y.csv` — serie mensual del premio a 30 años, 3 curvas.
- `term_premium_acm_full.csv` — panel completo (todos los plazos).
- `term_premium_acm_summary.csv` — último valor + estadísticos por curva.
- `term_premium_acm_30y.png` — gráfico de las tres series a 30 años.
