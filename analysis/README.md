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

---

# Flujos de fondos mutuos por tipo de fondo (CMF)

Script: `flujos_fondos_mutuos.py`. Descarga de la CMF la consulta mensual
*Patrimonio, Rentabilidad, Partícipes y Valor de la Cuota de Fondos Mutuos*
(`fm.fm_bpr.php`, todas las administradoras), que trae para cada mes una fila por
tipo de fondo (Tipo 1 a 8) y el total del sistema.

| Tipo | Descripción CMF |
|---|---|
| 1 | Deuda de corto plazo, duración ≤ 90 días (money market) |
| 2 | Deuda de corto plazo, duración ≤ 365 días |
| 3 | Deuda de mediano y largo plazo |
| 4 | Mixto |
| 5 | Instrumentos de capitalización (renta variable) |
| 6 | Libre inversión |
| 7 | Estructurado |
| 8 | Dirigido a inversionistas calificados |

## Cómo se calcula el flujo

La CMF no publica aportes y rescates agregados por tipo (la cartola diaria por
fondo, que sí los trae, está protegida con captcha). Por eso el **flujo neto** se
calcula como la variación de patrimonio que no explica la rentabilidad del mes:

    flujo_t = patrimonio_t − patrimonio_{t−1} · (1 + rentabilidad nominal_t)

Positivo = entradas netas (aportes > rescates). Está en millones de pesos
corrientes. El patrimonio de fondos en dólares/euros lo informa la CMF ya
convertido a pesos, así que en esos fondos el flujo implícito recoge también parte
del efecto cambiario.

**Tipo 1 (money market)** tiene una estacionalidad fuerte de fin de mes (±2 a 7
billones, por rescates de liquidez de empresas para remuneraciones e impuestos).
Conviene leerlo en sumas de 12 meses o anuales, no mes a mes.

## Resultado: últimos 12 meses (oct-2025 a sep-2026)

| Tipo | Flujo neto 12m (miles de MM$) | % del patrimonio | Patrimonio sep-2026 (miles de MM$) |
|---|---:|---:|---:|
| 1 Deuda CP ≤ 90d | −1.152 | −4,6% | 25.026 |
| 2 Deuda CP ≤ 365d | −1.130 | −11,7% | 9.696 |
| 3 Deuda MP/LP | +1.490 | +10,7% | 13.910 |
| 4 Mixto | +217 | +21,2% | 1.022 |
| 5 Capitalización | +708 | +11,9% | 5.927 |
| 6 Libre inversión | **+6.158** | +16,6% | 36.997 |
| 7 Estructurado | −332 | −76,5% | 434 |
| 8 Inv. calificados | +280 | +26,9% | 1.039 |
| **Total sistema** | **+6.152** | +6,5% | 94.051 |

En el último año la plata salió de los fondos de deuda de corto plazo (Tipos 1 y 2)
y de los estructurados, y entró sobre todo a libre inversión (Tipo 6), a deuda de
mediano y largo plazo (Tipo 3) y a renta variable (Tipo 5).

## Reproducir

```bash
pip install pandas xlrd matplotlib
python3 flujos_fondos_mutuos.py                       # 2010-01 .. mes anterior
python3 flujos_fondos_mutuos.py --desde 2000-01 --hasta 2026-09
```

Las descargas quedan en `cache/cmf_fm_bpr/` (está en `.gitignore`). La CMF tarda
~8 s por mes, así que la primera corrida completa demora ~25 min. Con `--refrescar`
se vuelve a bajar todo; sirve porque la CMF corrige datos con reenvíos.

## Salidas (`outputs/`)

- `flujos_fondos_mutuos_por_tipo_mensual.csv` — flujo neto mensual (MM$), una columna por tipo.
- `flujos_fondos_mutuos_por_tipo_anual.csv` — flujo neto anual por tipo.
- `flujos_fondos_mutuos_por_tipo_long.csv` — panel completo: patrimonio, rentabilidad,
  partícipes, efecto rentabilidad, flujo neto, flujo como % del patrimonio, variación de partícipes.
- `flujos_fondos_mutuos_por_tipo.png` — suma móvil 12 meses (Tipo 1 y total arriba, Tipos 2–8 abajo).
