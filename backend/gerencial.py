"""Informe gerencial: ventas, agotados, cobertura, momentos, actividades, obsequios + modelo estadístico."""
import numpy as np
import pandas as pd

from asesores import agrupar
from lectura import ErrorArchivo, exigir, familia, fecha, fecha_hora, limpio, norm_txt, num, pares, r
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
    """Cantidades de obsequios entregados por tipo, regional y asesor.

    Cada visita con entrega trae dos filas: "SELECCIONE EL OBSEQUIO ENTREGADO" (tipo, en RESPUESTA 1) y
    "UNIDADES ENTREGADAS DEL OBSEQUIO" (unidades, en RESPUESTA 2). Se emparejan por ID_RUTA (la visita).
    Si una visita no trae unidades, cuenta 1.
    """
    exigir(df, ["PREGUNTA", "RESPUESTA_1"], "obsequios")
    ase = "NOMBRE_ASESOR" if "NOMBRE_ASESOR" in df else None
    vis = "ID_RUTA" if "ID_RUTA" in df else ("ID_REGISTRO" if "ID_REGISTRO" in df else None)
    d = pd.DataFrame({
        "preg": df["PREGUNTA"].map(norm_txt), "r1": df["RESPUESTA_1"].map(limpio),
        "r2": df["RESPUESTA_2"].map(limpio) if "RESPUESTA_2" in df else "",
        "asesor": df[ase].map(limpio) if ase else "", "reg": df["REGION"].map(limpio) if "REGION" in df else "",
        "pdv": num(df["ID_PV"]) if "ID_PV" in df else np.nan,
        "vis": df[vis].astype(str) if vis else df.index.astype(str),
    })
    tipo = d[d.preg.str.contains("SELECCIONE EL OBSEQUIO") & (d.r1 != "")]
    und = d[d.preg.str.contains("UNIDADES ENTREGADAS")]
    und = und.assign(u=num(und.r2.where(und.r2 != "", und.r1))).groupby("vis").u.sum()
    e = tipo.assign(u=tipo.vis.map(und).fillna(1).where(lambda s: s > 0, 1))
    out = {"kpi": {"entregas": int(len(e)), "unidades": r(e.u.sum(), 0), "tipos": int(e.r1.nunique())},
           "por_tipo": pares(e.groupby("r1").u.sum(), 0),
           "por_regional": pares(e.groupby("reg").u.sum(), 0),
           "por_asesor": pares(e.groupby("asesor").u.sum(), 0)}
    # PdV con entrega (lo usa el modelo "Obsequios y venta")
    si = d[d.preg.str.contains("ENTREGO OBSEQUIO") & d.r1.map(norm_txt).isin(["SI"])]
    out["_pdv_entrega"] = set(si.pdv.dropna().astype("int64")) | set(e.pdv.dropna().astype("int64"))
    return out


# Columna de ID de usuario y de nombre del asesor en cada archivo (el ID es el mismo en todos)
COL_ASESOR = {"ventas": ("ID_ASESOR", "ASESOR"), "agotados": ("ID_USUARIO", "NOMBRE_PROMOTOR"),
              "cobertura": ("ID_ASESOR", "ASESOR"), "momentos": ("ASESOR_ID", "NOMBRE_ASESOR"),
              "actividades": ("ID_USUARIO", "PROM_MERCADERISTA_SUPERVISOR"), "obsequios": ("ID_ASESOR", "NOMBRE_ASESOR")}


def _ids_nombres(arch: dict) -> pd.DataFrame:
    filas = []
    for k, df in arch.items():
        ci, cn = COL_ASESOR.get(k, (None, None))
        if ci in df and cn in df:
            filas.append(pd.DataFrame({"id": df[ci].astype(str).str.strip(), "n": df[cn].map(limpio)}))
    if not filas:
        return pd.DataFrame(columns=["id", "n"])
    t = pd.concat(filas)
    return t[(t.id != "") & (t.n != "")]


def unificar_nombres(arch: dict) -> dict:
    """Un nombre por asesor en todos los archivos: por ID de usuario (nombre más frecuente) y por similitud del nombre
    (STEPHANNY RODRIGUEZ = STHEPANY RODRIGUEZ MONTOYA)."""
    t = _ids_nombres(arch)
    if t.empty:
        return arch
    estandar = agrupar(t.n.value_counts().to_dict())
    por_id = t.assign(n=t.n.map(estandar)).groupby("id").n.agg(lambda s: s.mode().iloc[0])
    out = {}
    for k, df in arch.items():
        ci, cn = COL_ASESOR.get(k, (None, None))
        if ci in df and cn in df:
            propio = df[cn].map(limpio)
            df = df.assign(**{cn: df[ci].astype(str).str.strip().map(por_id).fillna(propio.map(estandar)).fillna(propio)})
        out[k] = df
    return out


def lista_asesores(arch: dict):
    """[[ids, nombre], ...]: un renglón por nombre estándar; `ids` son los ID de usuario separados por coma
    (un mismo asesor puede tener más de un usuario)."""
    t = _ids_nombres(arch)
    if t.empty:
        return []
    nom = t.groupby("id").n.agg(lambda s: s.mode().iloc[0])
    ids = nom.groupby(nom).apply(lambda s: ",".join(sorted(s.index)))
    return sorted([[i, n] for n, i in ids.items()], key=lambda x: x[1])


def analizar(arch: dict, asesor: str | None = None):
    """arch: {nombre: DataFrame} con cualquiera de: ventas, agotados, cobertura, momentos, actividades, obsequios.
    `asesor`: ID de usuario; si se indica, todo el informe se calcula solo con sus registros."""
    R, avisos = {}, []
    arch = unificar_nombres(arch)
    lista = lista_asesores(arch)
    if asesor:
        nombre = dict(lista).get(str(asesor))
        if not nombre:
            raise ErrorArchivo("El asesor elegido no aparece en los archivos.")
        suyos = set(str(asesor).split(","))
        filtrado = {}
        for k, df in arch.items():
            ci = COL_ASESOR.get(k, (None,))[0]
            d = df[df[ci].astype(str).str.strip().isin(suyos)] if ci in df else df.iloc[0:0]
            if len(d):
                filtrado[k] = d
            else:
                avisos.append(f"{nombre} no tiene registros en el archivo de {k}.")
        arch = filtrado
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
    R["lista_asesores"] = lista
    R["asesor"] = dict(lista).get(str(asesor)) if asesor else None
    # quitar auxiliares internos
    for sec in R.values():
        if isinstance(sec, dict):
            for k in [k for k in sec if k.startswith("_")]:
                sec.pop(k)
    return R
