"""Última cartera de Fondos Mutuos (CMF) y Fondos de Pensiones (SP) en un Excel.

Fuentes (ambas públicas):

* FFMM — CMF, Portal de Fondos Mutuos, módulo "Carteras Fondos Mutuos",
  anexo "Base de datos" (xlsx):
  https://www.cmfchile.cl/portal/estadisticas/626/w4-article-91849.html
* AFP — Superintendencia de Pensiones, Centro de Estadísticas, "Cartera de
  Inversiones" -> "Versión completa en formato Zip" (XML de la cartera
  desagregada):
  https://www.spensiones.cl/apps/centroEstadisticas/paginaCuadrosCCEE.php?menu=sci&menuN1=estfinfp&menuN2=NOID

Uso:
    python3 carteras_ffmm_afp.py --cmf carteras_ffmm.xlsx \
        --sp cartera_afp.zip --out carteras_ffmm_afp_202606.xlsx

Del XML de la SP se usan los cuadros:
    1  — diversificación por instrumento y total de activos por AFP y fondo
    11 — cartera nacional por emisor e instrumento (por AFP y tipo de fondo)
    21 — inversión en el extranjero por emisor, nemotécnico e instrumento
Las filas "total_afps" / "total_fondos" de los cuadros 11 y 21 se omiten
porque son sumas de las filas por AFP.
"""

from __future__ import annotations

import argparse
import zipfile
import xml.etree.ElementTree as ET
from collections import OrderedDict

import pandas as pd
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.indexed_list import IndexedList

NS = "{http://www.spensiones.cl/xml}"
AFPS = ["CAPITAL", "CUPRUM", "HABITAT", "MODELO", "PLANVITAL", "PROVIDA", "UNO"]
FONDOS = ["A", "B", "C", "D", "E"]

FONT = "Arial"
F_BASE = Font(name=FONT, size=10)
F_HDR = Font(name=FONT, size=10, bold=True, color="FFFFFF")
F_BOLD = Font(name=FONT, size=10, bold=True)
F_TITLE = Font(name=FONT, size=14, bold=True)
F_SUB = Font(name=FONT, size=11, bold=True)
F_NOTE = Font(name=FONT, size=9, italic=True, color="595959")
F_LINK = Font(name=FONT, size=10, color="0563C1", underline="single")
FILL_HDR = PatternFill("solid", fgColor="1F3864")
FILL_TOT = PatternFill("solid", fgColor="D9E1F2")
THIN = Side(style="thin", color="BFBFBF")
B_TOP = Border(top=Side(style="thin", color="000000"))

NUM0 = "#,##0;(#,##0);-"
NUM2 = "#,##0.00;(#,##0.00);-"
PCT2 = "0.00%;(0.00%);-"
PCT1 = "0.0%;(0.0%);-"


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def _f(x):
    if x is None:
        return None
    x = x.strip()
    return float(x) if x else None


def parse_sp(zip_path: str):
    """Stream-parse the SP desagregated portfolio XML (≈280 MB)."""
    zf = zipfile.ZipFile(zip_path)
    name = [n for n in zf.namelist() if n.lower().endswith(".xml")][0]

    periodo = fecha_pub = None
    positions = []      # cuadros 11 y 21, una fila por emisor / nemotécnico
    instr_rows = []     # mismo detalle, una fila por instrumento
    divers = []         # cuadro 1
    totales = {}        # (AFP, Fondo) -> (MM$, MMUS$)

    stack: list[str] = []
    listado = tipofondo = afp = agrup = None
    instrumentos: list[str] = []
    in_instr_hdr = False

    with zf.open(name) as fh:
        for ev, el in ET.iterparse(fh, events=("start", "end")):
            tag = el.tag.replace(NS, "")
            if ev == "start":
                stack.append(tag)
                if tag == "listado":
                    listado = el.get("numero")
                elif tag == "tipofondo":
                    tipofondo = el.get("codigo")
                    instrumentos = []
                elif tag == "total_fondos":
                    tipofondo = "Total"
                    instrumentos = []
                elif tag == "instrumentos":
                    in_instr_hdr = True
                elif tag == "agrupacion":
                    agrup = el.get("nombre")
                elif tag in ("afp", "total_afps") and "fila" not in stack:
                    afp = None if tag == "afp" else "TOTAL"
                continue

            # ---- end events ----
            stack.pop()
            if tag == "periodo" and periodo is None:
                periodo = el.text
            elif tag == "fecha_publicacion" and fecha_pub is None:
                fecha_pub = el.text
            elif tag == "instrumentos":
                in_instr_hdr = False
            elif tag == "glosa" and in_instr_hdr:
                instrumentos.append(el.text.strip())
            elif (tag == "nombre" and stack and stack[-1] == "afp"
                  and "fila" not in stack):
                afp = el.text.strip()
            elif tag == "fila":
                if listado == "1" and "listado_por_afp" in stack:
                    _parse_div_row(el, tipofondo, divers, totales)
                elif listado in ("11", "21") and afp not in (None, "TOTAL") \
                        and tipofondo in FONDOS:
                    _parse_pos_row(el, listado, tipofondo, afp, agrup,
                                   instrumentos, positions, instr_rows)
                el.clear()
            elif tag == "listado":
                el.clear()

    pos = pd.DataFrame(positions)
    ins = pd.DataFrame(instr_rows)
    div = pd.DataFrame(divers)
    tot = pd.DataFrame(
        [(a, f, v[0], v[1]) for (a, f), v in totales.items()],
        columns=["AFP", "Fondo", "Activos MM$", "Activos MMUS$"])
    return dict(periodo=periodo, fecha_pub=fecha_pub, pos=pos, ins=ins,
                div=div, tot=tot)


def _parse_div_row(el, fondo, divers, totales):
    glosa = el.findtext(NS + "glosa").strip()
    cols = el.find(NS + "columnas")
    row = OrderedDict(Fondo=fondo, Glosa=glosa)
    for a in cols.findall(NS + "afp"):
        nom = a.findtext(NS + "nombre").strip()
        pct = _f(a.findtext(NS + "porcentaje"))
        mp = _f(a.findtext(NS + "monto_pesos"))
        md = _f(a.findtext(NS + "monto_dolares"))
        row[nom] = pct
        if mp is not None or md is not None:
            cur = totales.get((nom, fondo), (None, None))
            totales[(nom, fondo)] = (mp if mp is not None else cur[0],
                                     md if md is not None else cur[1])
    t = cols.find(NS + "total")
    row["Total MM$"] = _f(t.findtext(NS + "monto_pesos"))
    row["Total MMUS$"] = _f(t.findtext(NS + "monto_dolares"))
    row["Total %"] = _f(t.findtext(NS + "porcentaje"))
    divers.append(row)


def _parse_pos_row(el, listado, fondo, afp, agrup, instrumentos,
                   positions, instr_rows):
    tipo = "Nacional" if listado == "11" else "Extranjera"
    emisor = (el.findtext(NS + "glosa") or "").strip()
    nemo = (el.findtext(NS + "nemotecnico") or "").strip() or None
    moneda = (el.findtext(NS + "moneda") or "").strip() or None
    pcts = [_f(i.findtext(NS + "porcentaje"))
            for i in el.find(NS + "columnas").findall(NS + "instrumento")]
    assert len(pcts) == len(instrumentos), (listado, fondo, afp, emisor)
    t = el.find(NS + "total")
    mp = _f(t.findtext(NS + "monto_pesos"))
    md = _f(t.findtext(NS + "monto_dolares"))
    used = [(c, p) for c, p in zip(instrumentos, pcts) if p is not None]
    base = OrderedDict([
        ("Tipo cartera", tipo), ("Fondo", fondo), ("AFP", afp),
        ("Sector emisor", agrup), ("Emisor", emisor),
        ("Nemotécnico", nemo), ("Moneda", moneda)])
    positions.append(OrderedDict(
        base, **{"Instrumentos": " ".join(c for c, _ in used),
                 "% del fondo (SP)": round(sum(p for _, p in used), 2) if used else None,
                 "Monto MM$": mp, "Monto MMUS$": md}))
    for c, p in used:
        instr_rows.append(OrderedDict(base, **{"Instrumento": c,
                                               "% del fondo (SP)": p}))


def parse_glosario(zip_path: str) -> dict:
    """Instrument code descriptions from the notes of cuadro 1."""
    zf = zipfile.ZipFile(zip_path)
    name = [n for n in zf.namelist() if n.lower().endswith(".xml")][0]
    out = OrderedDict()
    with zf.open(name) as fh:
        for ev, el in ET.iterparse(fh, events=("end",)):
            if el.tag == NS + "notas":
                k = (el.findtext(NS + "item") or "").strip()
                v = " ".join((el.findtext(NS + "glosa") or "").split())
                if k and not k.startswith("(") and k not in out:
                    out[k] = v
            elif el.tag == NS + "listado":
                if el.get("numero") == "2":
                    break
                el.clear()
    return out


def load_cmf(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="datos")
    df["rut_emisor"] = df["rut_emisor"].astype("Int64").astype(str).replace("<NA>", None)
    return df


# --------------------------------------------------------------------------
# Writing helpers
# --------------------------------------------------------------------------
def _cell(ws, value, font=F_BASE, fmt=None, fill=None, align=None, border=None):
    c = WriteOnlyCell(ws, value=value)
    c.font = font
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    if align:
        c.alignment = align
    if border:
        c.border = border
    return c


def _header(ws, cols):
    ws.append([_cell(ws, h, F_HDR, fill=FILL_HDR,
                     align=Alignment(wrap_text=True, vertical="center"))
               for h in cols])


def _widths(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _val(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v.item() if hasattr(v, "item") else v


# --------------------------------------------------------------------------
# Workbook
# --------------------------------------------------------------------------
def build(cmf: pd.DataFrame, sp: dict, glos: dict, out: str):
    wb = Workbook(write_only=True)
    # Arial as workbook default font (unstyled cells)
    wb._fonts = IndexedList([F_BASE])
    wb._named_styles["Normal"].font = F_BASE

    fecha_ffmm = str(int(cmf["fecha_mes"].iloc[0]))
    fecha_ffmm = f"{fecha_ffmm[:4]}-{fecha_ffmm[4:]}"

    # ---------------- sheet order ----------------
    ws_res = wb.create_sheet("Resumen")
    ws_ff = wb.create_sheet("FFMM_Fondos")
    ws_fc = wb.create_sheet("FFMM_Cartera")
    ws_af = wb.create_sheet("AFP_Fondos")
    ws_ac = wb.create_sheet("AFP_Cartera")
    ws_ai = wb.create_sheet("AFP_Instrumento")
    ws_ad = wb.create_sheet("AFP_Diversificacion")
    ws_g = wb.create_sheet("Glosario_AFP")
    ws_n = wb.create_sheet("Notas")

    # ================= FFMM_Cartera =================
    cmf = cmf.sort_values(["nombre_agf", "nombre_fondo", "base_origen",
                           "val_cierr"], ascending=[True, True, False, False])
    n_fc = len(cmf)
    fc_cols = [
        ("Periodo", 9, None), ("AGF", 18, None), ("RUN fondo", 9, "0"),
        ("Fondo", 38, None), ("Categoría AAFM", 22, None),
        ("Tipo cartera", 16, None), ("Nemotécnico", 18, None),
        ("Emisor", 36, None), ("RUT emisor", 11, None), ("País emisor", 16, None),
        ("Clase de activo", 14, None), ("Tipo instrumento", 11, None),
        ("Descripción instrumento", 40, None), ("Clasificación instrumento", 24, None),
        ("Clasif. riesgo", 10, None), ("Duración (días)", 10, NUM0),
        ("Valor cierre (MMUS$)", 13, NUM2), ("% del fondo", 10, PCT2)]
    _widths(ws_fc, [w for _, w, _ in fc_cols])
    ws_fc.freeze_panes = "E2"
    ws_fc.auto_filter.ref = f"A1:{get_column_letter(len(fc_cols))}{n_fc + 1}"
    _header(ws_fc, [c for c, _, _ in fc_cols])
    ff_last = 1 + cmf["fo_run"].nunique()
    for r, row in enumerate(cmf.itertuples(index=False), start=2):
        vals = [fecha_ffmm, row.nombre_agf, int(row.fo_run), row.nombre_fondo,
                row.familia_estudios, row.base_origen, row.nemotecnico,
                row.nombre_emisor, row.rut_emisor, row.nombre_pais_emisor,
                row.primer_layer, row.tipo_instrumento, row.descripcion_tipoinst,
                row.clasificacion_instrumentos_txt, row.clas_riesg,
                row.duracion_fondo, row.val_cierr,
                f"=IFERROR(Q{r}/INDEX(FFMM_Fondos!$F$2:$F${ff_last},"
                f"MATCH(C{r},FFMM_Fondos!$A$2:$A${ff_last},0)),0)"]
        ws_fc.append([_cell(ws_fc, _val(v), fmt=f) for v, (_, _, f) in zip(vals, fc_cols)])

    # ================= FFMM_Fondos =================
    funds = (cmf.groupby("fo_run", sort=False)
             .agg(fondo=("nombre_fondo", "first"), agf=("nombre_agf", "first"),
                  cat=("familia_estudios", "first"))
             .reset_index().sort_values(["agf", "fondo"]))
    FC = "FFMM_Cartera"
    rng = lambda col: f"{FC}!${col}$2:${col}${n_fc + 1}"  # noqa: E731
    ff_cols = [("RUN fondo", 9, "0"), ("Fondo", 38, None), ("AGF", 18, None),
               ("Categoría AAFM", 22, None), ("N° instrumentos", 10, NUM0),
               ("Valor cartera (MMUS$)", 13, NUM2), ("% Nacional", 9, PCT1),
               ("% Extranjera", 9, PCT1), ("% Deuda", 9, PCT1),
               ("% Intermediación", 11, PCT1), ("% Acciones", 9, PCT1),
               ("% Alternativos", 10, PCT1), ("% Otros", 9, PCT1)]
    _widths(ws_ff, [w for _, w, _ in ff_cols])
    ws_ff.freeze_panes = "C2"
    ws_ff.auto_filter.ref = f"A1:{get_column_letter(len(ff_cols))}{ff_last}"
    _header(ws_ff, [c for c, _, _ in ff_cols])
    share = lambda r, col, crit: (  # noqa: E731
        f"=IFERROR(SUMIFS({rng('Q')},{rng('C')},$A{r},{rng(col)},\"{crit}\")/$F{r},0)")
    for r, f in enumerate(funds.itertuples(index=False), start=2):
        vals = [int(f.fo_run), f.fondo, f.agf, f.cat,
                f"=COUNTIF({rng('C')},A{r})", f"=SUMIF({rng('C')},A{r},{rng('Q')})",
                share(r, "F", "Cartera Nacional"), share(r, "F", "Cartera Extranjera"),
                share(r, "K", "Deuda"), share(r, "K", "Intermediación"),
                share(r, "K", "Acciones"), share(r, "K", "Alternativos"),
                share(r, "K", "Otros")]
        ws_ff.append([_cell(ws_ff, _val(v), fmt=fm) for v, (_, _, fm) in zip(vals, ff_cols)])
    assert ff_last == len(funds) + 1

    # ================= AFP_Fondos =================
    tot = sp["tot"]
    tot = tot[tot["Fondo"].isin(FONDOS)].copy()
    tot["k"] = tot["AFP"].map(AFPS.index) * 10 + tot["Fondo"].map(FONDOS.index)
    tot = tot.sort_values("k")
    pos = sp["pos"]
    n_ac = len(pos)
    AC = "AFP_Cartera"
    arng = lambda col: f"{AC}!${col}$2:${col}${n_ac + 1}"  # noqa: E731
    ad_last = len(sp["div"]) + 1
    AD = "AFP_Diversificacion"
    ext_ofi = lambda fondo_ref, afp_ref: (  # noqa: E731
        f"=IFERROR(INDEX({AD}!$D$2:$J${ad_last},MATCH({fondo_ref}&\"|TOTAL EXTRANJERO\","
        f"{AD}!$A$2:$A${ad_last},0),MATCH(\"% \"&{afp_ref},{AD}!$D$1:$J$1,0))/100,0)")
    af_cols = [("Clave", 13, None), ("AFP", 12, None), ("Fondo", 7, None),
               ("Activos MM$ (SP)", 15, NUM0), ("Activos MMUS$ (SP)", 13, NUM0),
               ("% Extranjero oficial (SP, cuadro 1)", 12, PCT1),
               ("Posiciones nacionales MM$ (cuadro 11)", 15, NUM0),
               ("Posiciones extranjeras MM$ (cuadro 21)", 15, NUM0),
               ("Disponible y otros MM$ (residuo)", 15, NUM0)]
    _widths(ws_af, [w for _, w, _ in af_cols])
    ws_af.freeze_panes = "D2"
    _header(ws_af, [c for c, _, _ in af_cols])
    af_last = len(tot) + 1
    for r, t in enumerate(tot.itertuples(index=False), start=2):
        vals = [f"{t.AFP}|{t.Fondo}", t.AFP, t.Fondo, t._2, t._3,
                ext_ofi(f"$C{r}", f"$B{r}"),
                f"=SUMIFS({arng('K')},{arng('A')},\"Nacional\",{arng('C')},$B{r},{arng('B')},$C{r})",
                f"=SUMIFS({arng('K')},{arng('A')},\"Extranjera\",{arng('C')},$B{r},{arng('B')},$C{r})",
                f"=D{r}-G{r}-H{r}"]
        ws_af.append([_cell(ws_af, _val(v), fmt=fm, font=F_BASE) for v, (_, _, fm) in zip(vals, af_cols)])
    tr = af_last + 1
    ws_af.append([
        _cell(ws_af, "TOTAL", F_BOLD, fill=FILL_TOT, border=B_TOP),
        _cell(ws_af, None, fill=FILL_TOT, border=B_TOP),
        _cell(ws_af, None, fill=FILL_TOT, border=B_TOP)] + [
        _cell(ws_af, f"=SUM({c}2:{c}{af_last})", F_BOLD, NUM0, FILL_TOT, border=B_TOP)
        for c in "DE"] + [
        _cell(ws_af, f"=IFERROR(INDEX({AD}!$M$2:$M${ad_last},MATCH(\"Total|TOTAL EXTRANJERO\","
                     f"{AD}!$A$2:$A${ad_last},0))/100,0)", F_BOLD, PCT1, FILL_TOT, border=B_TOP)] + [
        _cell(ws_af, f"=SUM({c}2:{c}{af_last})", F_BOLD, NUM0, FILL_TOT, border=B_TOP)
        for c in "GHI"])
    ws_af.append([])
    for note in [
            "Activos y % extranjero oficial: cuadro 1 de la SP (diversificación por instrumentos).",
            "Posiciones nacionales / extranjeras: suma de AFP_Cartera (cuadros 11 y 21, incluye derivados a valor de mercado).",
            "La clasificación de los cuadros 11/21 no calza 1:1 con el cuadro 1: el cuadro 21 incluye p.ej. cuotas de fondos de "
            "inversión nacionales con subyacente extranjero (CFID/CFIV) y banco en el extranjero (CC3). Para el % extranjero usar la columna oficial.",
            "Disponible y otros = Activos - posiciones; puede ser negativo por derivados y diferencias de clasificación."]:
        ws_af.append([_cell(ws_af, note, F_NOTE)])

    # ================= AFP_Cartera =================
    pos = pos.sort_values(["AFP", "Fondo", "Tipo cartera", "Monto MM$"],
                          ascending=[True, True, False, False])
    ac_cols = [("Tipo cartera", 11, None), ("Fondo", 7, None), ("AFP", 11, None),
               ("Sector emisor", 14, None), ("Emisor", 38, None),
               ("Nemotécnico", 15, None), ("Moneda", 12, None),
               ("Instrumentos", 14, None), ("% del fondo (SP, 2 dec.)", 11, NUM2),
               ("Periodo", 9, None), ("Monto MM$", 13, NUM2),
               ("Monto MMUS$", 12, NUM2), ("% del fondo (calc.)", 10, "0.000%;(0.000%);-")]
    _widths(ws_ac, [w for _, w, _ in ac_cols])
    ws_ac.freeze_panes = "F2"
    ws_ac.auto_filter.ref = f"A1:{get_column_letter(len(ac_cols))}{n_ac + 1}"
    _header(ws_ac, [c for c, _, _ in ac_cols])
    for r, p in enumerate(pos.itertuples(index=False), start=2):
        vals = list(p[:9]) + [sp["periodo"], p[9], p[10],
                              f"=IFERROR(K{r}/INDEX(AFP_Fondos!$D$2:$D${af_last},"
                              f"MATCH(C{r}&\"|\"&B{r},AFP_Fondos!$A$2:$A${af_last},0)),0)"]
        ws_ac.append([_cell(ws_ac, _val(v), fmt=fm) for v, (_, _, fm) in zip(vals, ac_cols)])

    # ================= AFP_Instrumento =================
    ins = sp["ins"].sort_values(["AFP", "Fondo", "Tipo cartera", "Emisor", "Instrumento"],
                                ascending=[True, True, False, True, True])
    ai_cols = [("Tipo cartera", 11, None), ("Fondo", 7, None), ("AFP", 11, None),
               ("Sector emisor", 14, None), ("Emisor", 38, None),
               ("Nemotécnico", 15, None), ("Moneda", 12, None),
               ("Instrumento", 11, None), ("% del fondo (SP)", 11, NUM2)]
    _widths(ws_ai, [w for _, w, _ in ai_cols])
    ws_ai.freeze_panes = "F2"
    ws_ai.auto_filter.ref = f"A1:I{len(ins) + 1}"
    _header(ws_ai, [c for c, _, _ in ai_cols])
    for p in ins.itertuples(index=False):
        ws_ai.append([_cell(ws_ai, _val(v), fmt=fm) for v, (_, _, fm) in zip(p, ai_cols)])

    # ================= AFP_Diversificacion =================
    div = sp["div"]
    ad_cols = ([("Clave", 30, None), ("Fondo", 7, None), ("Instrumento / agrupación", 38, None)]
               + [(f"% {a}", 10, NUM2) for a in AFPS]
               + [("Total MM$", 14, NUM2), ("Total MMUS$", 12, NUM2), ("Total %", 9, NUM2)])
    _widths(ws_ad, [w for _, w, _ in ad_cols])
    ws_ad.freeze_panes = "D2"
    ws_ad.auto_filter.ref = f"A1:{get_column_letter(len(ad_cols))}{len(div) + 1}"
    _header(ws_ad, [c for c, _, _ in ad_cols])
    for d in div.to_dict("records"):
        is_tot = d["Glosa"].upper().startswith("TOTAL")
        vals = [f"{d['Fondo']}|{d['Glosa']}", d["Fondo"], d["Glosa"]] + [d.get(a) for a in AFPS] + \
               [d["Total MM$"], d["Total MMUS$"], d["Total %"]]
        ws_ad.append([_cell(ws_ad, _val(v), F_BOLD if is_tot else F_BASE, fm,
                            FILL_TOT if is_tot else None)
                      for v, (_, _, fm) in zip(vals, ad_cols)])

    # ================= Glosario =================
    _widths(ws_g, [10, 110])
    _header(ws_g, ["Código", "Descripción (SP, notas del cuadro 1)"])
    for k, v in glos.items():
        ws_g.append([_cell(ws_g, k), _cell(ws_g, v)])

    # ================= Resumen =================
    _build_resumen(ws_res, cmf, sp, fecha_ffmm, n_fc, ff_last, af_last, ext_ofi, ad_last)

    # ================= Notas =================
    _build_notas(ws_n, sp, fecha_ffmm)

    wb.save(out)


def _build_resumen(ws, cmf, sp, fecha_ffmm, n_fc, ff_last, af_last, ext_ofi, ad_last):
    _widths(ws, [34, 14, 16, 12, 12, 14, 14, 14, 14, 14])
    n = [0]  # last written row

    def put(cells=()):
        ws.append(list(cells))
        n[0] += 1
        return n[0]

    A = lambda v, **k: _cell(ws, v, **k)  # noqa: E731
    H = lambda hs: put([A(h, font=F_HDR, fill=FILL_HDR,  # noqa: E731
                          align=Alignment(wrap_text=True, vertical="center")) for h in hs])
    T = dict(font=F_BOLD, fill=FILL_TOT, border=B_TOP)

    put([A("Cartera de Fondos Mutuos y Fondos de Pensiones", font=F_TITLE)])
    put([A(f"FFMM: cartera al {fecha_ffmm} (CMF). AFP: cartera al {sp['periodo']} "
           f"(SP, publicada {sp['fecha_pub']}). Ver hoja Notas para fuentes y unidades.",
           font=F_NOTE)])
    put()

    FF = lambda c: f"FFMM_Fondos!${c}$2:${c}${ff_last}"  # noqa: E731
    FCr = lambda c: f"FFMM_Cartera!${c}$2:${c}${n_fc + 1}"  # noqa: E731

    # --- 1. FFMM por AGF ---
    put([A("1. Fondos mutuos por administradora (AGF)", font=F_SUB)])
    H(["AGF", "N° fondos", "Valor cartera (MMUS$)", "% industria", "% extranjera"])
    agfs = cmf.groupby("nombre_agf").val_cierr.sum().sort_values(ascending=False).index.tolist()
    first = n[0] + 1
    last = n[0] + len(agfs)
    tr = last + 1
    for i, agf in enumerate(agfs):
        r = first + i
        put([A(agf),
             A(f"=COUNTIF({FF('C')},A{r})", fmt=NUM0),
             A(f"=SUMIF({FF('C')},A{r},{FF('F')})", fmt=NUM0),
             A(f"=IFERROR(C{r}/C${tr},0)", fmt=PCT1),
             A(f"=IFERROR(SUMIFS({FCr('Q')},{FCr('B')},A{r},{FCr('F')},\"Cartera Extranjera\")/C{r},0)", fmt=PCT1)])
    assert put([A("TOTAL", **T),
                A(f"=SUM(B{first}:B{last})", fmt=NUM0, **T),
                A(f"=SUM(C{first}:C{last})", fmt=NUM0, **T),
                A(f"=SUM(D{first}:D{last})", fmt=PCT1, **T),
                A(f"=IFERROR(SUMIFS({FCr('Q')},{FCr('F')},\"Cartera Extranjera\")/C{tr},0)", fmt=PCT1, **T)]) == tr
    tot_ffmm = f"$C${tr}"
    put()

    # --- 2. FFMM por clase de activo / instrumento ---
    put([A("2. Fondos mutuos por clase de activo e instrumento", font=F_SUB)])
    H(["Clase de activo", "Valor (MMUS$)", "% industria"])
    for c in cmf.groupby("primer_layer").val_cierr.sum().sort_values(ascending=False).index:
        r = n[0] + 1
        put([A(c), A(f"=SUMIF({FCr('K')},A{r},{FCr('Q')})", fmt=NUM0),
             A(f"=IFERROR(B{r}/{tot_ffmm},0)", fmt=PCT1)])
    put()
    H(["Clasificación instrumento (15 mayores)", "Valor (MMUS$)", "% industria"])
    top = (cmf.groupby("clasificacion_instrumentos_txt").val_cierr.sum()
           .sort_values(ascending=False).head(15).index)
    for c in top:
        r = n[0] + 1
        put([A(c), A(f"=SUMIF({FCr('N')},A{r},{FCr('Q')})", fmt=NUM0),
             A(f"=IFERROR(B{r}/{tot_ffmm},0)", fmt=PCT1)])
    put()

    # --- 3. AFP: activos por AFP x Fondo ---
    AF = lambda c: f"AFP_Fondos!${c}$2:${c}${af_last}"  # noqa: E731
    put([A("3. Fondos de pensiones: activos por AFP y tipo de fondo (MM$)", font=F_SUB)])
    H(["AFP"] + [f"Fondo {f}" for f in FONDOS] + ["Total", "% sistema", "% extranjero (SP)"])
    f4 = n[0] + 1
    l4 = n[0] + len(AFPS)
    t4 = l4 + 1
    for i, a in enumerate(AFPS):
        r = f4 + i
        put([A(a)] +
            [A(f"=SUMIFS({AF('D')},{AF('B')},$A{r},{AF('C')},\"{f}\")", fmt=NUM0) for f in FONDOS] +
            [A(f"=SUM(B{r}:F{r})", fmt=NUM0, font=F_BOLD),
             A(f"=IFERROR(G{r}/G${t4},0)", fmt=PCT1),
             A(ext_ofi('"Total"', f"$A{r}"), fmt=PCT1)])
    assert put([A("TOTAL", **T)] +
               [A(f"=SUM({c}{f4}:{c}{l4})", fmt=NUM0, **T) for c in "BCDEFG"] +
               [A(f"=SUM(H{f4}:H{l4})", fmt=PCT1, **T),
                A(f"=IFERROR(INDEX(AFP_Diversificacion!$M$2:$M${ad_last},MATCH(\"Total|TOTAL EXTRANJERO\","
                  f"AFP_Diversificacion!$A$2:$A${ad_last},0))/100,0)", fmt=PCT1, **T)]) == t4
    put([A("Total activos en MMUS$", font=F_BOLD), A(f"=SUM({AF('E')})", font=F_BOLD, fmt=NUM0)])
    put()

    # --- 4. AFP: top emisores ---
    put([A("4. Fondos de pensiones: 15 mayores emisores (todas las AFP y fondos)", font=F_SUB)])
    H(["Emisor", "Tipo cartera", "Monto MM$", "Monto MMUS$", "% activos sistema"])
    pos = sp["pos"]
    topem = (pos.groupby(["Emisor", "Tipo cartera"])["Monto MM$"].sum()
             .sort_values(ascending=False).head(15).reset_index())
    ACr = lambda c: f"AFP_Cartera!${c}$2:${c}${len(pos) + 1}"  # noqa: E731
    for e, tc in zip(topem["Emisor"], topem["Tipo cartera"]):
        r = n[0] + 1
        put([A(e), A(tc),
             A(f"=SUMIFS({ACr('K')},{ACr('E')},A{r},{ACr('A')},B{r})", fmt=NUM0),
             A(f"=SUMIFS({ACr('L')},{ACr('E')},A{r},{ACr('A')},B{r})", fmt=NUM0),
             A(f"=IFERROR(C{r}/$G${t4},0)", fmt=PCT1)])


def _build_notas(ws, sp, fecha_ffmm):
    _widths(ws, [28, 120])
    A = lambda v, **k: _cell(ws, v, **k)  # noqa: E731
    ws.append([A("Fuentes, unidades y advertencias", font=F_TITLE)])
    ws.append([])
    rows = [
        ("FFMM — fuente", "CMF, Portal de Fondos Mutuos, módulo «Carteras Fondos Mutuos», anexo «Base de datos» (xlsx)."),
        ("FFMM — URL", "https://www.cmfchile.cl/portal/estadisticas/626/w4-article-91849.html"),
        ("FFMM — fecha", f"Cartera al cierre de {fecha_ffmm}. Es la última publicada por la CMF en el portal (actualización trimestral; "
                         "la próxima, con datos a septiembre 2026, aún no estaba disponible al 05-11-2026)."),
        ("FFMM — cobertura", "Cartera nacional y extranjera de los fondos mutuos, a nivel de instrumento (nemotécnico). "
                             "No incluye carteras de opciones ni futuros."),
        ("FFMM — unidad del valor", "La CMF no informa la unidad de «val_cierr». Se infiere millones de US$: los fondos en dólares "
                                   "traen valores con ≤3 decimales (sin conversión) y los fondos en pesos traen decimales de conversión; "
                                   "además la suma (≈US$106.900 millones, 440 fondos) es consistente con el patrimonio de "
                                   "US$100.884 millones en 441 fondos que informó la CMF para junio 2026 (la cartera es bruta de pasivos). "
                                   "El «% del fondo» no depende de la unidad."),
        ("FFMM — % del fondo", "Valor del instrumento / suma de valores de la cartera del fondo (nacional + extranjera), igual que la metodología CMF."),
        ("AFP — fuente", "Superintendencia de Pensiones, Centro de Estadísticas, «Cartera de Inversiones» → «Versión completa en formato Zip» "
                         "(XML de la cartera desagregada)."),
        ("AFP — URL", "https://www.spensiones.cl/apps/centroEstadisticas/paginaCuadrosCCEE.php?menu=sci&menuN1=estfinfp&menuN2=NOID"),
        ("AFP — fecha", f"Cartera al {sp['periodo']} (publicada {sp['fecha_pub']}). La SP publica la cartera desagregada con 4 meses de rezago; "
                        "es la más reciente con detalle por emisor. La cartera agregada mensual (hasta 2026-09) no se pudo descargar: "
                        "la aplicación de la SP devolvía error 404 al momento de construir este archivo."),
        ("AFP — cuadros usados", "Cuadro 1 (diversificación y total de activos por AFP y fondo) → AFP_Diversificacion y AFP_Fondos. "
                                 "Cuadro 11 (cartera nacional por emisor e instrumento) y cuadro 21 (inversión en el extranjero por emisor, "
                                 "nemotécnico e instrumento) → AFP_Cartera y AFP_Instrumento. Se omiten las filas de totales del sistema "
                                 "(son sumas de las filas por AFP)."),
        ("AFP — unidades", "Montos en millones de pesos (MM$) y millones de dólares (MMUS$) al dólar observado del último día hábil del mes. "
                           "Porcentajes de la SP respecto del total de activos del fondo (tipo A–E) de cada AFP, redondeados a 2 decimales "
                           "(por eso posiciones chicas aparecen como 0,00). «% del fondo (calc.)» = Monto MM$ / Activos MM$ del fondo, sin redondeo."),
        ("AFP — granularidad", "Cartera nacional: una fila por emisor (los instrumentos del emisor se listan en «Instrumentos»; el desglose por "
                               "instrumento está en AFP_Instrumento). Cartera extranjera: una fila por emisor y nemotécnico (ISIN/código)."),
        ("AFP — derivados", "Los cuadros 11 y 21 incluyen forwards y swaps (códigos W*, Y*, SN*) a valor de mercado, que pueden ser negativos."),
        ("Fórmulas", "Las hojas Resumen, FFMM_Fondos, AFP_Fondos y las columnas «% del fondo» se calculan con fórmulas sobre las hojas de detalle; "
                     "si se filtran o editan datos de detalle, los resúmenes se recalculan."),
        ("Construcción", "Script: analysis/carteras_ffmm_afp.py (repo cmf)."),
    ]
    for k, v in rows:
        ws.append([A(k, font=F_BOLD, align=Alignment(vertical="top")),
                   A(v, align=Alignment(wrap_text=True, vertical="top"))])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cmf", required=True, help="xlsx 'Base de datos' Carteras FFMM (CMF)")
    ap.add_argument("--sp", required=True, help="zip cartera desagregada (SP)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    cmf = load_cmf(a.cmf)
    sp = parse_sp(a.sp)
    glos = parse_glosario(a.sp)
    print(f"FFMM: {len(cmf):,} filas, {cmf.fo_run.nunique()} fondos | "
          f"AFP {sp['periodo']}: {len(sp['pos']):,} posiciones, {len(sp['ins']):,} filas instrumento, "
          f"{len(sp['tot'])} totales AFP/fondo")
    build(cmf, sp, glos, a.out)
    print("ok ->", a.out)


if __name__ == "__main__":
    main()
