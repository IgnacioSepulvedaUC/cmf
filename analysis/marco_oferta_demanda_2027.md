# Oferta y demanda de bonos 2027 — marco conceptual

Segmentos: **Gobierno** (BTP/BTU de Tesorería), **Bancarios** y **Corporativos**
(mercado local chileno). Este documento fija el marco teórico; la estimación
numérica viene después.

---

## 1. Definiciones

| Concepto | Definición | Para qué sirve |
|---|---|---|
| Oferta bruta | Monto colocado en el año | Es el "ruido" que ve el mercado (licitaciones, colocaciones) |
| Vencimientos | Amortizaciones + vencimientos finales del stock vivo | Parte que es sólo refinanciamiento |
| **Oferta neta** | Oferta bruta − vencimientos − rescates/recompras = ΔStock | Lo que el mercado debe *absorber de verdad* |
| Oferta neta de caja | Oferta bruta − (amortizaciones + cupones) | Los cupones y amortizaciones vuelven a los inversionistas y en buena parte se reinvierten |
| Oferta en duración | Σ monto × duración (o DV01) | Riesgo de tasa que se transfiere al mercado; es lo que mueve el *term premium* |

Regla práctica: **se proyecta la oferta neta en duración**. Un año con mucha
emisión bruta pero de refinanciamiento a plazo corto presiona poco; un año con
emisión neta larga en UF presiona mucho al tramo largo.

**Demanda** = flujo nuevo de recursos de cada inversionista × la fracción que asigna
a cada segmento + reinversión de cupones y amortizaciones que recibe +
cambios de portafolio (Δ de la ponderación × activos).

---

## 2. Equilibrio: cantidades y precios

El mercado siempre se cierra: lo que se emite, alguien lo tiene. Por eso **no se
estima un "déficit de bonos"**, sino un **exceso de oferta ex-ante** a los
precios actuales, que se ajusta vía tasas/spreads:

```
Exceso_s = Oferta_neta_s(2027) − Demanda_neta_s(2027 | tasas actuales)
Δ tasa/spread_s ≈ Exceso_s / (elasticidad de la demanda_s)
```

Teoría de soporte:

- **Hábitat preferido (Vayanos–Vila)**: los inversionistas con preferencia por
  plazos (AFP, aseguradoras) absorben oferta a cambio de premio; más oferta en
  duración → mayor *term premium*. Esto conecta directo con el ACM que ya está en
  `acm_term_premium.py`: el term premium es la variable de precio en la que
  impacta el desbalance.
- **Sustitución imperfecta entre segmentos**: más oferta soberana sube las tasas
  soberanas y desplaza la demanda por bancarios/corporativos (*crowding out*),
  presionando también sus spreads. Los tres segmentos se modelan **juntos**,
  no por separado.
- **Sensibilidad a la tasa base**: la oferta corporativa y bancaria responde al
  costo (tasa + spread), la soberana casi no; la demanda de fondos mutuos responde
  a la trayectoria esperada de la TPM.

---

## 3. Oferta por segmento

### 3.1 Gobierno — exógena, de política fiscal

La determina la identidad de financiamiento del Fisco:

```
Necesidad bruta de financiamiento =
      Déficit fiscal efectivo (Balance base caja)
    + Amortizaciones de deuda que vencen en 2027
    + Otros requerimientos (capitalizaciones, aportes, bonos de reconocimiento)
    − Uso de activos (FEES, FRP, otros activos del Tesoro)
```

Luego se reparte: **local vs. externa**, **pesos (BTP) vs. UF (BTU)** y **plazos**.

- Fuentes: Ley de Presupuestos 2027 (autorización de endeudamiento), Informe de
  Finanzas Públicas (IFP) de octubre 2026, calendario de licitaciones de Hacienda
  (se publica a inicios de 2027) y meta de deuda/regla fiscal.
- Casi no responde a tasas en el corto plazo → es el **shock de oferta** del
  sistema. Lo que sí puede variar es la mezcla de monedas y plazos (la oferta en
  duración).
- Escenarios: cumplimiento de la meta de balance estructural vs. desvío
  (precio del cobre, ingresos tributarios, gasto); cambio de gobierno en marzo
  2026 y su política fiscal.
- Complemento: deuda del Banco Central (PDBC/BCP) y sus compras/ventas, que
  cambian la oferta de "activos seguros" que efectivamente queda en el mercado.

### 3.2 Bancarios — función del balance de los bancos

Los bancos emiten bonos para financiar activos de largo plazo (sobre todo
**hipotecarios en UF**) y calzar plazos:

```
Emisión bruta_b ≈ Vencimientos_b
                + φ · Δ(colocaciones de largo plazo, esp. hipotecarias)
                − Δ(otras fuentes de largo plazo: depósitos a plazo largo, externo)
                + Requerimientos regulatorios (subordinados / AT1 de Basilea III; NSFR)
```

Determinantes: crecimiento del crédito, costo relativo bono vs. depósito vs.
financiamiento externo, demanda de las aseguradoras por UF larga, y factores
específicos (la emisión de 2022–24 estuvo inflada por el pago de la FCIC al
Banco Central; eso ya no se repite).

### 3.3 Corporativos — decisión de financiamiento de la empresa

```
Emisión bruta_c ≈ ρ · Vencimientos_c                 (tasa de refinanciamiento)
                + β · Inversión (FBCF, concesiones, energía)
                + γ · (Costo préstamo bancario / bono externo swapeado − costo bono local)
                + eventos (M&A, prepagos)
```

- La empresa elige entre bono local, crédito bancario y bono externo; el
  diferencial de costo es clave.
- Ciclo: en tasas bajando, las empresas adelantan emisión y refinancian (prepagos).
- Concentración: pocos emisores grandes explican gran parte del volumen → conviene
  una lista explícita de vencimientos y "pipeline" de inscripciones ante la CMF.

---

## 4. Demanda por tipo de inversionista

| Inversionista | Motor del flujo 2027 | Preferencia | Comentarios |
|---|---|---|---|
| **AFP (fondos de pensiones)** | Cotizaciones − pensiones/traspasos + reinversión | Gob + bancarios + corporativos, UF largo | Reforma previsional: alza gradual de la cotización del empleador (más flujo nuevo) y transición a fondos generacionales (cambia la mezcla renta fija/variable y local/extranjero). Riesgo de retiros de fondos |
| **Cías. de seguros de vida** | Primas de rentas vitalicias + reinversión | UF muy largo, corporativos y bancarios | Calce de pasivos (TSA/suficiencia de activos); demanda poco sensible a precio, muy sensible a plazo |
| **Fondos mutuos / FI** | Aportes netos (procíclicos con la caída de la TPM) | Corto/mediano, pesos | Demanda elástica a tasas |
| **Bancos** | Liquidez regulatoria (LCR), colateral BCCh | Gobierno y BCCh | Demandan principalmente soberanos |
| **Extranjeros** | Diferencial de tasas, costo de cobertura, riesgo global | BTP en pesos | Factor más volátil; elegibilidad Euroclear e índices |
| **Banco Central** | Programas extraordinarios | Gobierno/bancarios | Sólo en escenarios de estrés |

Forma general para cada inversionista *i* y segmento *s*:

```
Demanda neta_{i,s} = w_{i,s} · (Flujo nuevo_i + Reinversión_i)  +  Δw_{i,s} · Activos_i
```

- `w_{i,s}`: participación actual del segmento en la cartera (de la cartera
  agregada de cada sector).
- `Δw`: cambios esperados de asignación (regulación, límites de inversión, multifondos,
  diferencial de retorno esperado).
- La **reinversión** se calcula con los mismos flujos de cupones y amortizaciones
  del lado de la oferta: es el puente entre los dos lados.

---

## 5. Cómo se arma la estimación (pasos)

1. **Stock y calendario de vencimientos 2027** por segmento, moneda (CLP/UF) y plazo.
2. **Oferta 2027**: gobierno con la regla de financiamiento + calendario oficial;
   bancarios y corporativos con modelo de refinanciamiento + crecimiento neto,
   calibrado 2015–2026. Tres escenarios (bajo / base / alto).
3. **Demanda 2027** por inversionista: activos × flujo × ponderaciones.
4. **Balance** por segmento y en duración → exceso de oferta ex-ante.
5. **Traducción a precios**: elasticidad histórica de spreads / term premium
   (ACM) a la oferta neta en duración.
6. **Validación**: aplicar el mismo marco "fuera de muestra" a 2024–2026.

---

## 6. Datos: qué hay y qué falta

**En el repo (`cmf_bonos_flujos_emisiones.xlsx`, CMF):**

- `FLUJOS`: cupones y amortizaciones pagados por bancarios y corporativos,
  2015-01 a 2026-05 → reinversión y patrón de amortizaciones.
- `EMISIONES`: colocaciones (`aumento_colocacion`) y catálogo de series
  (vencimiento, plazo, tasa, monto inscrito) → oferta bruta histórica y calendario
  de vencimientos.
- Curvas (`curva.parquet`) y term premium ACM → variable de precio.

Problemas detectados que hay que limpiar antes de estimar:

- Filas `TOTAL` y filas de notas al pie mezcladas con datos en corporativos.
- Montos con errores de unidad (p. ej. cupones de ~$26 billones en una sola serie),
  que distorsionan los totales anuales (2019, 2022, 2023).
- Colocaciones corporativas sólo desde 2024; vencimientos corporativos
  incompletos (~19% con fecha).
- **No hay datos de gobierno ni de demanda**.

**Falta (externo):**

- Gobierno: DIPRES/Hacienda (IFP, Ley de Presupuestos 2027, calendario de emisiones, stock de deuda por bono).
- Demanda: Superintendencia de Pensiones (cartera agregada AFP), CMF (cartera de
  aseguradoras), AAFM (fondos mutuos), BCCh (Cuentas Nacionales por sector
  institucional, tenencias de no residentes), DCV (custodia por tipo de tenedor).
