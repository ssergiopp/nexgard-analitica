"""Informe gerencial: ventas, agotados, cobertura, momentos, actividades, obsequios + modelo estadístico."""
import numpy as np
import pandas as pd

from lectura import exigir, familia, fecha, fecha_hora, limpio, norm_txt, num, pares, r
from modelo import comparar_grupos, correlacion, serie_diaria


def _pct(a, b):
    return r(a / b * 100) if b else None


def ventas(df):
    exigir(df, ["CANTIDAD", "PRECIO_TOTAL", "DESCRIPCION_PRODUCTO", "ASESOR", "FECHA_CAPTURA"], "ventas")
    d = pd.DataFrame({
        "q": num(df["CANTIDAD"]).fillna(0), "v": num(df["PRECIO_TOTAL"]).fillna(0),
        "sku": df["DESCRIPCION_PRODUCTO"].map(limpio), "asesor": df["ASESOR"].map(limpio),
        "f": fecha(df["FECHA_CAPTURA"]),
        "reg": df["REGIONAL"].map(limpio) if "REGIONAL" in df else "",
        "estado": df["ESTADO_PEDIDO"].map(limpio) if "ESTADO_PEDIDO" in df else "",
        "pedido": df["ID_PEDIDO"] if "ID_PEDIDO" in df else df.index,
        "pdv": num(df["ID_SUCURSAL"]) if "ID_SUCURSAL" in df else np.nan,
    })
    # Líneas con cantidad ≥ 100 y ≥ 20 veces la mediana del SKU: error de digitación, se excluyen.
    med = d.groupby("sku").q.transform("median")
    raro = d[(d.q >= 100) & (d.q >= 20 * med)]
    miles = lambda v: f"{int(v):,}".replace(",", ".")  # noqa: E731
    alertas = [f"Excluida: {limpio(df.loc[i, 'SUCURSAL']) if 'SUCURSAL' in df else ''} · {x.sku} · {miles(x.q)} unidades "
               f"({x.f.strftime('%d/%m/%Y') if pd.notna(x.f) else 's/f'}); la mediana del SKU es {miles(med[i])}."
               for i, x in raro.iterrows()]
    d = d.drop(raro.index)
    tot = d.v.sum()
    fds = d[d.f.dt.dayofweek.isin([4, 5, 6])].v.sum()  # vie, sáb, dom
    ped = d.groupby("pedido").v.sum()
    asesor = d.groupby("asesor").agg(q=("q", "sum"), v=("v", "sum"), pedidos=("pedido", "nunique")).sort_values("v", ascending=False)
    return {
        "kpi": {"total": r(tot, 0), "unidades": r(d.q.sum(), 0), "pedidos": int(d.pedido.nunique()),
                "ticket": r(ped.mean(), 0), "pdv": int(d.pdv.nunique()),
                "pct_fds": _pct(fds, tot), "pct_semana": _pct(tot - fds, tot),
                "desde": d.f.min().strftime("%d/%m/%Y") if d.f.notna().any() else None,
                "hasta": d.f.max().strftime("%d/%m/%Y") if d.f.notna().any() else None},
        "alertas": alertas,
        "sku_unidades": pares(d.groupby("sku").q.sum(), 0),
        "sku_valor": pares(d.groupby("sku").v.sum() / 1e6, 2),
        "familia": pares(d.groupby(d.sku.map(familia)).v.sum() / 1e6, 2),
        "regional": pares(d.groupby("reg").v.sum() / 1e6, 2),
        "estado": pares(d.groupby("estado").v.sum() / 1e6, 2),
        "asesores": [[a, r(x.q, 0), r(x.v / 1e6, 2), int(x.pedidos)] for a, x in asesor.iterrows()],
        "_diaria": d.groupby("f").v.sum() / 1e6,
        "_pdv": d.dropna(subset=["pdv"]).groupby("pdv").v.sum(),
        "_idx": d.index,  # filas válidas (sin atípicas), las usa comisiones
    }


def agotados(df):
    exigir(df, ["AGOTADO", "PRESENTE", "NO_MANEJANTE", "PRODUCTO"], "agotados")
    reg = "REGION" if "REGION" in df else "REGIONAL"
    d = pd.DataFrame({
        "a": num(df["AGOTADO"]).fillna(0), "p": num(df["PRESENTE"]).fillna(0), "n": num(df["NO_MANEJANTE"]).fillna(0),
        "sku": df["PRODUCTO"].map(limpio), "reg": df[reg].map(limpio) if reg in df else "",
        "f": fecha(df["FECHA_CAPTURA"]) if "FECHA_CAPTURA" in df else pd.NaT,
        "causa": df["CAUSAL_AGOTADO"].map(limpio) if "CAUSAL_AGOTADO" in df else "",
        "pdv": num(df["ID_SUCURSAL"]) if "ID_SUCURSAL" in df else np.nan,
        "pdv_n": df["SUCURSAL"].map(limpio) if "SUCURSAL" in df else "",
    })
    d["fam"] = d.sku.map(familia)

    def tri(g):
        t = g[["p", "a", "n"]].sum()
        s = t.sum()
        return [r(t.p / s * 100), r(t.a / s * 100), r(t.n / s * 100)] if s else [0, 0, 0]

    def pct_ag(g):  # agotado sobre puntos que manejan el SKU
        m = g.a.sum() + g.p.sum()
        return g.a.sum() / m * 100 if m else np.nan

    ag = d[d.a > 0]
    generica = ag.causa.map(norm_txt).isin(["", "AGOTADO", "NO APLICA"])
    sem = d.dropna(subset=["f"])
    sem = sem.groupby(sem.f.dt.to_period("W-SUN").dt.start_time).apply(pct_ag, include_groups=False)
    total = d[["a", "p", "n"]].sum().sum()
    pdv_top = d.groupby("pdv_n").a.sum()
    return {
        "kpi": {"pct_agotado": _pct(d.a.sum(), total), "pct_agotado_manejantes": r(pct_ag(d)),
                "pct_presente": _pct(d.p.sum(), total), "pct_no_manejante": _pct(d.n.sum(), total),
                "registros": int(len(d)), "pdv": int(d.pdv.nunique()),
                "pct_causal_generica": _pct(generica.sum(), len(ag))},
        "regional": [[k, tri(g)] for k, g in d.groupby("reg")],
        "familia": [[k, tri(g)] for k, g in d.groupby("fam")],
        "semanas": [[k.strftime("%d/%m"), r(v)] for k, v in sem.items()],
        "sku": pares(d.groupby("sku").apply(pct_ag, include_groups=False).dropna()),
        "causas": pares(d[d.a > 0].groupby("causa").size(), 0, 10),
        "pdv_top": pares(pdv_top[pdv_top > 0], 0, 15),
        "_pdv": d.dropna(subset=["pdv"]).groupby("pdv").apply(pct_ag, include_groups=False),
    }


def cobertura(df):
    exigir(df, ["EFECTIVIDAD", "ESTADO", "ASESOR", "ID_PV"], "cobertura (efectividad de visitas)")
    reg = "REGION" if "REGION" in df else "DIVISION"
    d = pd.DataFrame({
        "ef": df["EFECTIVIDAD"].map(norm_txt) == "EFECTIVA", "estado": df["ESTADO"].map(limpio),
        "asesor": df["ASESOR"].map(limpio), "pdv": num(df["ID_PV"]),
        "reg": df[reg].map(limpio) if reg in df else "",
        "ini": fecha_hora(df["HORA_INICIAL"]) if "HORA_INICIAL" in df else pd.NaT,
        "fin": fecha_hora(df["HORA_FINAL"]) if "HORA_FINAL" in df else pd.NaT,
    })
    d["min"] = (d.fin - d.ini).dt.total_seconds() / 60
    n = len(d)
    nov = d[~d.ef].groupby("estado").size().sort_values(ascending=False)
    ef = d[d.ef]
    dur = ef[(ef["min"] > 0) & (ef["min"] < 600)]
    return {
        "kpi": {"cobertura": _pct(d.ef.sum(), n), "visitas": int(n), "efectivas": int(d.ef.sum()),
                "pdv_visitados": int(ef.pdv.nunique()), "min_visita": r(dur["min"].median())},
        "novedades": [[k, int(v), _pct(v, n)] for k, v in nov.items()],
        "pdv_por_asesor": pares(ef.groupby("asesor").pdv.nunique(), 0),
        "cobertura_asesor": pares(d.groupby("asesor").ef.mean() * 100),
        "cobertura_regional": pares(d.groupby("reg").ef.mean() * 100),
        "min_asesor": pares(dur.groupby("asesor")["min"].median()),
        "_pdv_visitados": set(ef.pdv.dropna().astype("int64")),
    }


def momentos(df):
    exigir(df, ["NOMBRE_ACTIVIDAD", "NOMBRE_ASESOR", "FECHA_INICIO"], "momentos")
    d = pd.DataFrame({
        "act": df["NOMBRE_ACTIVIDAD"].map(limpio), "sub": df.get("NOMBRE_SUBACTIVIDAD", "").map(limpio) if "NOMBRE_SUBACTIVIDAD" in df else "",
        "asesor": df["NOMBRE_ASESOR"].map(limpio), "ini": fecha_hora(df["FECHA_INICIO"]),
        "q": num(df["CANT_UNIDADES"]) if "CANT_UNIDADES" in df else np.nan,
        "prod": df["NOMBRE_PRODUCTO"].map(limpio) if "NOMBRE_PRODUCTO" in df else "",
    })
    d["dia"] = d.ini.dt.normalize()
    # Jornada: primera marca a última marca del asesor en el día
    j = d.dropna(subset=["ini"]).groupby(["asesor", "dia"]).ini.agg(["min", "max"])
    j["h"] = (j["max"] - j["min"]).dt.total_seconds() / 3600
    j = j[j.h > 0]
    con_q = d[d.q > 0]
    return {
        "kpi": {"registros": int(len(d)), "dias_asesor": int(len(j)), "horas_jornada": r(j.h.median()),
                "unidades": r(con_q.q.sum(), 0)},
        "actividades": pares(d.groupby("act").size(), 0, 15),
        "subactividades": pares(d.groupby("sub").size(), 0, 15),
        "horas_asesor": pares(j.groupby(level=0).h.median()),
        "unidades_producto": pares(con_q.groupby("prod").q.sum(), 0, 15),
    }


def actividades(df, pdv_visitados=None):
    exigir(df, ["TIPO_ACTIVIDAD", "SUBTIPO_ACTIVIDAD", "ID_SUCURSAL"], "actividades")
    reg = next((c for c in ("REGIONAL", "REGION") if c in df), None)
    ase = next((c for c in ("PROM_MERCADERISTA_SUPERVISOR", "ASESOR") if c in df), None)
    d = pd.DataFrame({
        "tipo": df["TIPO_ACTIVIDAD"].map(limpio), "sub": df["SUBTIPO_ACTIVIDAD"].map(limpio),
        "pdv": num(df["ID_SUCURSAL"]), "reg": df[reg].map(limpio) if reg else "",
        "asesor": df[ase].map(limpio) if ase else "",
    })
    n = len(d)
    pdv = set(d.pdv.dropna().astype("int64"))
    out = {
        "kpi": {"registros": int(n), "pdv_con_actividad": len(pdv)},
        "regional": pares(d.groupby("reg").size() / n * 100),
        "tipo": pares(d.groupby("tipo").size() / n * 100),
        "subtipo": pares(d.groupby("sub").size() / n * 100),
        "asesor": pares(d.groupby("asesor").pdv.nunique(), 0),
        "_pdv": pdv,
    }
    if pdv_visitados:
        out["kpi"]["pct_pdv_visitados_con_actividad"] = _pct(len(pdv & pdv_visitados), len(pdv_visitados))
    return out


def obsequios(df):
    exigir(df, ["PREGUNTA", "RESPUESTA_1"], "obsequios")
    ase = "NOMBRE_ASESOR" if "NOMBRE_ASESOR" in df else None
    d = pd.DataFrame({
        "preg": df["PREGUNTA"].map(limpio), "resp": df["RESPUESTA_1"].map(limpio),
        "asesor": df[ase].map(limpio) if ase else "", "reg": df["REGION"].map(limpio) if "REGION" in df else "",
        "pdv": num(df["ID_PV"]) if "ID_PV" in df else np.nan,
    })
    d = d[d.resp != ""]
    out = {"kpi": {"registros": int(len(d))}, "preguntas": []}
    for p, g in d.groupby("preg", sort=False):
        c = g.resp.map(norm_txt).value_counts()
        out["preguntas"].append({"pregunta": p, "n": int(len(g)),
                                 "opciones": [[k, int(v), _pct(v, len(g))] for k, v in c.head(12).items()]})
    entrega = d[d.preg.map(norm_txt).str.contains("ENTREGO OBSEQUIO")]
    if len(entrega):
        si = entrega.resp.map(norm_txt).isin(["SI", "SÍ"])
        out["kpi"]["pct_entrega"] = _pct(si.sum(), len(entrega))
        out["entrega_asesor"] = pares(entrega.assign(si=si).groupby("asesor").si.mean() * 100)
        out["entrega_regional"] = pares(entrega.assign(si=si).groupby("reg").si.mean() * 100)
        out["_pdv_entrega"] = set(entrega[si].pdv.dropna().astype("int64"))
    return out


def analizar(arch: dict):
    """arch: {nombre: DataFrame} con cualquiera de: ventas, agotados, cobertura, momentos, actividades, obsequios."""
    R, avisos = {}, []
    if "cobertura" in arch:
        R["cobertura"] = cobertura(arch["cobertura"])
    for k, f in (("ventas", ventas), ("agotados", agotados), ("momentos", momentos), ("obsequios", obsequios)):
        if k in arch:
            R[k] = f(arch[k])
    if "actividades" in arch:
        R["actividades"] = actividades(arch["actividades"], R.get("cobertura", {}).get("_pdv_visitados"))

    modelo = {}
    if "ventas" in R:
        modelo["serie"] = serie_diaria(R["ventas"]["_diaria"])
        vp = R["ventas"]["_pdv"]
        if "actividades" in R:
            con = vp.index.isin(list(R["actividades"]["_pdv"]))
            modelo["actividad_vs_venta"] = comparar_grupos(vp[con] / 1e6, vp[~con] / 1e6,
                                                           "Con actividad", "Sin actividad")
        if "agotados" in R:
            modelo["agotados_vs_venta"] = correlacion(R["agotados"]["_pdv"], vp / 1e6)
        if "obsequios" in R and R["obsequios"].get("_pdv_entrega") is not None:
            con = vp.index.isin(list(R["obsequios"]["_pdv_entrega"]))
            modelo["obsequio_vs_venta"] = comparar_grupos(vp[con] / 1e6, vp[~con] / 1e6, "Con obsequio", "Sin entrega registrada")
    else:
        avisos.append("Sin archivo de ventas no se calcula el modelo de tendencia ni el pronóstico.")
    R["modelo"] = modelo
    R["avisos"] = avisos
    # quitar auxiliares internos
    for sec in R.values():
        if isinstance(sec, dict):
            for k in [k for k in sec if k.startswith("_")]:
                sec.pop(k)
    return R
