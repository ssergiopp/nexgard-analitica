"""Comisiones por asesor (mercaimpulsador). El backend entrega los indicadores; el pago se calcula en la página
porque depende de la meta, los montos y la calificación de activaciones que se escriben ahí.

  Sell Out   = unidades vendidas (VENTA TEÓRICA + Forms de activaciones del mismo periodo) ÷ meta mensual de unidades
  Cobertura  = visitas efectivas (EFECTIVIDAD_VISITAS) ÷ visitas programadas (suma de FRECUENCIA MES en PDVS)
  Activaciones = calificación manual
  SGI        = días con inicio y fin de jornada (MOMENTOS) ÷ días trabajados
  Pago de cada componente = monto × min(cumplimiento, 100 %)
"""
import pandas as pd

from asesores import agrupar, nombres
from forms import celdas, leer_celda
from gerencial import ventas as _ventas_base
from lectura import exigir, fecha, limpio, norm_txt, num, r
from encuestas import _maestro_pdv


def _forms_por_asesor(forms: pd.DataFrame, desde, hasta, id_nombre: dict, oficiales, cedulas: dict, corr: dict) -> dict:
    """Unidades de Forms por asesor oficial en [desde, hasta]. Quién reporta se identifica por cédula -> ID de usuario
    (hoja FORM de VENTA TEÓRICA o histórico) -> asesor de la plataforma; si no hay ID, por similitud del nombre con la
    hoja PDVS. Las celdas en duda no se cuentan (salvo que ya estén corregidas en el histórico)."""
    c = celdas(forms)
    if desde is not None:
        c = c[(c.fecha >= desde) & (c.fecha <= hasta)]
    filas, revision = [], 0
    for x in c.itertuples(index=False):
        if (x.id_resp, x.sku) in corr:
            q = corr[(x.id_resp, x.sku)][0]
        else:
            L = leer_celda(x.texto)
            if L["estado"] == "duda":
                revision += 1
                continue
            q = L["q"] or 0
        if q:
            filas.append((x.id_resp, x.cedula, q))
    f = pd.DataFrame(filas, columns=["id_resp", "cedula", "q"])
    of = set(oficiales)

    def quien(ced):
        nom, ida = cedulas.get(ced, ("", ""))
        if ida and ida in id_nombre:
            return id_nombre[ida]
        if nom:
            m = agrupar({**{o: 1 for o in oficiales}, nom: 1}, oficiales).get(nom)
            if m in of:
                return m
        return None
    f["asesor"] = f.cedula.map({ced: quien(ced) for ced in f.cedula.unique()}) if len(f) else []
    sin = f[f.asesor.isna()]
    sin_nom = sin.assign(n=sin.cedula.map(lambda c: cedulas.get(c, ("", ""))[0] or f"CC {c}")).groupby("n").q.sum()
    return {"unidades": f.dropna(subset=["asesor"]).groupby("asesor").q.sum(),
            "resumen": {"desde": desde.strftime("%d/%m/%Y") if desde is not None else None,
                        "hasta": hasta.strftime("%d/%m/%Y") if hasta is not None else None,
                        "respuestas": int(f.id_resp.nunique()), "unidades": r(f.q.sum(), 0),
                        "asignadas": r(f.dropna(subset=["asesor"]).q.sum(), 0), "en_revision": revision,
                        "sin_asesor": [[k, r(v, 0)] for k, v in sin_nom.sort_values(ascending=False).items()]}}


def analizar(ventas: pd.DataFrame, cobertura: pd.DataFrame, rutero: pd.DataFrame, momentos: pd.DataFrame,
             forms: pd.DataFrame | None = None, cedulas: dict | None = None, corr: dict | None = None):
    maestro = _maestro_pdv(rutero)
    exigir(rutero, ["FRECUENCIA_MES"], "rutero (hoja PDVS)")
    exigir(ventas, ["CANTIDAD", "ID_ASESOR", "ID_SUCURSAL", "ASESOR"], "ventas")
    exigir(cobertura, ["EFECTIVIDAD", "ID_ASESOR", "ID_PV", "ASESOR"], "cobertura (efectividad de visitas)")
    exigir(momentos, ["NOMBRE_ACTIVIDAD", "ASESOR_ID", "PUNTO_VENTA_ID", "NOMBRE_ASESOR", "FECHA_INICIO"], "momentos")

    # Programadas: FRECUENCIA MES de los puntos a cargo (misma fila del maestro)
    frec = rutero.assign(_id=num(rutero["ID_PDV"]), _f=num(rutero["FRECUENCIA_MES"]).fillna(0))
    frec = frec.dropna(subset=["_id"]).drop_duplicates("_id").set_index("_id")["_f"]
    prog = maestro.assign(f=maestro["id"].map(frec).fillna(0)).groupby("asesor")["f"].sum()

    # Sell Out: unidades por asesor, sin líneas atípicas (misma regla del informe gerencial)
    base = _ventas_base(ventas)
    v = ventas.loc[ventas.index.isin(base["_idx"])]
    v = v.assign(_a=nombres(maestro, v, "ID_ASESOR", "ID_SUCURSAL", "ASESOR"), _q=num(v["CANTIDAD"]).fillna(0))
    unidades = v.groupby("_a")["_q"].sum()
    u_plat = unidades.copy()
    fv0 = fecha(ventas["FECHA_CAPTURA"]) if "FECHA_CAPTURA" in ventas else pd.Series(dtype="datetime64[ns]")
    u_forms, forms_res = pd.Series(dtype=float), None
    if forms is not None:
        # Forms trae todo el histórico: se toma el mismo periodo de la venta teórica (desde el día 1 de su primer mes).
        desde = fv0.min().replace(day=1) if fv0.notna().any() else None
        hasta = fv0.max() if fv0.notna().any() else None
        id_nombre = (v.assign(_id=v["ID_ASESOR"].map(lambda s: str(s).strip().removesuffix(".0")))
                     .groupby("_id")["_a"].agg(lambda s: s.mode().iloc[0]).to_dict())
        F = _forms_por_asesor(forms, desde, hasta, id_nombre, list(maestro["asesor"].unique()), cedulas or {}, corr or {})
        u_forms, forms_res = F["unidades"], F["resumen"]
        unidades = unidades.add(u_forms, fill_value=0)

    c = cobertura.assign(_a=nombres(maestro, cobertura, "ID_ASESOR", "ID_PV", "ASESOR"),
                         _ef=cobertura["EFECTIVIDAD"].map(norm_txt) == "EFECTIVA")
    efectivas = c.groupby("_a")["_ef"].sum()
    # Desglose del motivo (columna ESTADO) de las visitas efectivas y no efectivas, por asesor
    est = c["ESTADO"].map(limpio).replace("", "SIN ESTADO") if "ESTADO" in c else pd.Series("SIN ESTADO", index=c.index)
    desg = c.assign(_e=est).groupby(["_a", "_ef", "_e"]).size()
    motivos = {}
    for (a, ef, e), n in desg.items():
        motivos.setdefault(a, {"efectiva": [], "no_efectiva": []})["efectiva" if ef else "no_efectiva"].append([e, int(n)])
    for d in motivos.values():
        for k in d:
            d[k].sort(key=lambda x: -x[1])

    m = momentos.assign(_a=nombres(maestro, momentos, "ASESOR_ID", "PUNTO_VENTA_ID", "NOMBRE_ASESOR"),
                        _d=fecha(momentos["FECHA_INICIO"]), _act=momentos["NOMBRE_ACTIVIDAD"].map(norm_txt))
    m = m.dropna(subset=["_d"])
    dia = m.groupby(["_a", "_d"])["_act"].agg(lambda s: ("INICIO JORNADA" in set(s)) and ("FIN DE JORNADA" in set(s)))
    dias = dia.groupby(level=0).size()
    completos = dia.groupby(level=0).sum()

    todos = sorted(set(prog.index) | set(unidades.index) | set(efectivas.index) | set(dias.index))
    filas = []
    for a in todos:
        p, e, d, k = prog.get(a, 0), efectivas.get(a, 0), dias.get(a, 0), completos.get(a, 0)
        filas.append({
            "asesor": a, "unidades": r(unidades.get(a, 0), 0),
            "unidades_plataforma": r(u_plat.get(a, 0), 0), "unidades_forms": r(u_forms.get(a, 0), 0),
            "efectivas": int(e), "programadas": r(p, 0), "pct_cobertura": r(e / p * 100) if p else None,
            "dias": int(d), "jornadas_completas": int(k), "pct_sgi": r(k / d * 100) if d else None,
            "en_maestro": bool(a in prog.index),
            "motivos": motivos.get(a, {"efectiva": [], "no_efectiva": []}),
        })
    fv = fecha(ventas["FECHA_CAPTURA"]) if "FECHA_CAPTURA" in ventas else pd.Series(dtype="datetime64[ns]")
    periodo = (f"{fv.min():%d/%m/%Y} a {fv.max():%d/%m/%Y}" if fv.notna().any() else "")
    return {"asesores": filas, "periodo_ventas": periodo, "alertas": base["alertas"], "forms": forms_res}
