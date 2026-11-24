"""Histórico de ventas guardado en este PC (SQLite), para no subir la base cada vez.

Dos fuentes que se suman (las ventas de Forms son adicionales a las de la plataforma):
- PLATAFORMA: VENTA TEÓRICA (hoja de pedidos). Cada carga agrega líneas; una línea repetida no se cuenta dos veces.
- FORMS: base cruda del link de activaciones. Cada carga reemplaza la anterior (la base trae todo el histórico).
  Las cantidades se leen del texto (forms.py); las celdas dudosas se corrigen a mano y la corrección se conserva.
La carpeta se puede cambiar con la variable de entorno NEXGARD_DATOS (p. ej. una carpeta de OneDrive).
"""
import hashlib
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from forms import celdas, leer_celda, sku_canon
from lectura import ErrorArchivo, fecha, limpio, num, r

RAIZ = Path(__file__).resolve().parent.parent
CARPETA = Path(os.environ.get("NEXGARD_DATOS") or RAIZ / "datos")
BD = CARPETA / "historico.sqlite"
FUENTES = {"plataforma": ("PLATAFORMA",), "forms": ("FORMS",), "ambas": ("PLATAFORMA", "FORMS")}

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS plataforma(clave TEXT PRIMARY KEY, fecha TEXT, asesor TEXT, id_asesor TEXT, regional TEXT,
  ciudad TEXT, pdv TEXT, id_pdv REAL, pedido TEXT, sku TEXT, unidades REAL, valor REAL, archivo TEXT, cargado TEXT);
CREATE TABLE IF NOT EXISTS forms(id_resp INTEGER, sku TEXT, fecha TEXT, cedula TEXT, regional TEXT, pdv TEXT, texto TEXT,
  PRIMARY KEY(id_resp, sku));
CREATE TABLE IF NOT EXISTS forms_corr(id_resp INTEGER, sku TEXT, unidades REAL, precio REAL, PRIMARY KEY(id_resp, sku));
CREATE TABLE IF NOT EXISTS cedulas(cedula TEXT PRIMARY KEY, nombre TEXT, id_asesor TEXT);
CREATE TABLE IF NOT EXISTS cargas(cuando TEXT, fuente TEXT, archivo TEXT, filas INTEGER, nuevas INTEGER);
"""


def _con():
    CARPETA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(BD)
    c.executescript(_ESQUEMA)
    return c


def _ced(v) -> str:
    return re.sub(r"\.0$", "", limpio(v))


# ---------- Carga ----------
def cargar_plataforma(hojas: dict, archivo: str) -> dict:
    """hojas: {nombre: DataFrame} de un archivo de VENTA TEÓRICA. Usa la hoja de pedidos (no 'VENTAS FIN DE SEMANA',
    que repite pedidos, ni 'HISTORICO', que es de otro año) y, si existe, la hoja FORM para nombrar las cédulas."""
    req = {"CANTIDAD", "PRECIO_TOTAL", "DESCRIPCION_PRODUCTO", "FECHA_CAPTURA", "ID_PEDIDO"}
    cand = {k: v for k, v in hojas.items() if req <= set(v.columns)
            and not re.search(r"FIN\s*DE\s*SEMANA|HISTORICO", k.upper())}
    if not cand:
        raise ErrorArchivo(f"'{archivo}' no tiene una hoja de pedidos de VENTA TEÓRICA "
                           "(CANTIDAD, PRECIO_TOTAL, DESCRIPCION_PRODUCTO, FECHA_CAPTURA, ID_PEDIDO).")
    df = max(cand.values(), key=len)
    t = pd.DataFrame({
        "fecha": fecha(df["FECHA_CAPTURA"]).dt.strftime("%Y-%m-%d"),
        "asesor": df["ASESOR"].map(limpio) if "ASESOR" in df else "",
        "id_asesor": df["ID_ASESOR"].map(_ced) if "ID_ASESOR" in df else "",
        "regional": df["REGIONAL"].map(lambda v: limpio(v).upper()) if "REGIONAL" in df else "",
        "ciudad": df["CIUDAD"].map(limpio) if "CIUDAD" in df else "",
        "pdv": df["SUCURSAL"].map(limpio) if "SUCURSAL" in df else "",
        "id_pdv": num(df["ID_SUCURSAL"]) if "ID_SUCURSAL" in df else None,
        "pedido": df["ID_PEDIDO"].map(_ced),
        "sku": df["DESCRIPCION_PRODUCTO"].map(lambda v: sku_canon(v) or limpio(v)),
        "unidades": num(df["CANTIDAD"]).fillna(0), "valor": num(df["PRECIO_TOTAL"]).fillna(0),
    }).dropna(subset=["fecha"])
    # Clave de la línea: pedido + producto + cantidad + valor (la misma línea en dos archivos no se duplica).
    prod = df.loc[t.index, "ID_PRODUCTO"].map(_ced) if "ID_PRODUCTO" in df else t.sku
    t["clave"] = [hashlib.md5(f"{a}|{b}|{c}|{d}".encode()).hexdigest() for a, b, c, d in
                  zip(t.pedido, prod, t.unidades, t.valor)]
    t = t.drop_duplicates("clave").assign(archivo=archivo, cargado=datetime.now().isoformat(timespec="seconds"))
    with _con() as c:
        antes = c.execute("SELECT COUNT(*) FROM plataforma").fetchone()[0]
        c.executemany(f"INSERT OR IGNORE INTO plataforma({','.join(t.columns)}) VALUES({','.join('?' * len(t.columns))})",
                      t.astype(object).where(t.notna(), None).values.tolist())
        nuevas = c.execute("SELECT COUNT(*) FROM plataforma").fetchone()[0] - antes
        # Cédula -> nombre e ID de usuario (hoja FORM del mismo libro), para nombrar a quien reporta en Forms.
        fm = next((v for k, v in hojas.items() if {"CEDULA", "NOMBRE_COMPLETO"} <= set(v.columns)), None)
        if fm is not None:
            m = fm[["CEDULA", "NOMBRE_COMPLETO"] + (["ID_ASESOR"] if "ID_ASESOR" in fm else [])].dropna(subset=["CEDULA"])
            c.executemany("INSERT OR REPLACE INTO cedulas VALUES(?,?,?)",
                          [(_ced(x.CEDULA), limpio(x.NOMBRE_COMPLETO), _ced(getattr(x, "ID_ASESOR", ""))) for x in m.itertuples()])
        c.execute("INSERT INTO cargas VALUES(?,?,?,?,?)", (datetime.now().isoformat(timespec="seconds"), "PLATAFORMA",
                                                           archivo, len(t), nuevas))
    return {"archivo": archivo, "filas": len(t), "nuevas": nuevas, "repetidas": len(t) - nuevas}


def cargar_forms(df: pd.DataFrame, archivo: str) -> dict:
    """Reemplaza la base de Forms por la nueva (la base cruda trae todas las respuestas)."""
    t = celdas(df)
    t["fecha"] = t.fecha.dt.strftime("%Y-%m-%d")
    with _con() as c:
        c.execute("DELETE FROM forms")
        c.executemany("INSERT OR REPLACE INTO forms VALUES(?,?,?,?,?,?,?)",
                      t[["id_resp", "sku", "fecha", "cedula", "regional", "pdv", "texto"]].values.tolist())
        c.execute("INSERT INTO cargas VALUES(?,?,?,?,?)", (datetime.now().isoformat(timespec="seconds"), "FORMS",
                                                           archivo, int(t.id_resp.nunique()), int(t.id_resp.nunique())))
    return {"archivo": archivo, "respuestas": int(t.id_resp.nunique())}


def borrar(fuente: str, mes: str | None = None):
    with _con() as c:
        if fuente == "PLATAFORMA":
            c.execute("DELETE FROM plataforma" + (" WHERE substr(fecha,1,7)=?" if mes else ""), (mes,) if mes else ())
        elif fuente == "FORMS":
            c.execute("DELETE FROM forms")


def corregir(id_resp: int, sku: str, unidades, precio):
    with _con() as c:
        if unidades in (None, ""):
            c.execute("DELETE FROM forms_corr WHERE id_resp=? AND sku=?", (id_resp, sku))
        else:
            c.execute("INSERT OR REPLACE INTO forms_corr VALUES(?,?,?,?)",
                      (id_resp, sku, float(unidades), float(precio) if precio not in (None, "") else None))


# ---------- Lectura ----------
def _plataforma(c) -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM plataforma", c)


def _precio_ref(p: pd.DataFrame) -> tuple[dict, dict]:
    """Precio unitario mediano de cada SKU en la plataforma, por mes y en todo el histórico."""
    p = p[(p.unidades > 0) & (p.valor > 0)].assign(pu=lambda d: d.valor / d.unidades, mes=lambda d: d.fecha.str[:7])
    return p.groupby(["sku", "mes"]).pu.median().to_dict(), p.groupby("sku").pu.median().to_dict()


def _forms(c, plat: pd.DataFrame) -> pd.DataFrame:
    f = pd.read_sql("SELECT * FROM forms", c)
    if f.empty:
        return f
    corr = pd.read_sql("SELECT * FROM forms_corr", c).set_index(["id_resp", "sku"])
    ced = pd.read_sql("SELECT * FROM cedulas", c).set_index("cedula")
    por_mes, global_ = _precio_ref(plat)
    filas = []
    for x in f.itertuples(index=False):
        k = (x.id_resp, x.sku)
        if k in corr.index:
            q, p0 = corr.loc[k, "unidades"], corr.loc[k, "precio"]
            L = {"q": q, "p": None if pd.isna(p0) else p0, "estado": "corregida", "motivo": ""}
        else:
            L = leer_celda(x.texto)
        if L["estado"] == "cero" or (L["q"] == 0 and L["estado"] != "duda"):
            continue
        p, est = L["p"], L["estado"]
        if p is None and est != "duda":
            p = por_mes.get((x.sku, x.fecha[:7]), global_.get(x.sku))
            est = "precio_ref" if p is not None else "sin_precio"
        nom = ced.loc[x.cedula] if x.cedula in ced.index else None
        filas.append({"id_resp": x.id_resp, "sku": x.sku, "fecha": x.fecha, "cedula": x.cedula,
                      "asesor": nom["nombre"] if nom is not None else (f"CC {x.cedula}" if x.cedula.isdigit() else x.cedula),
                      "id_asesor": (nom["id_asesor"] or f"CC{x.cedula}") if nom is not None else f"CC{x.cedula}",
                      "regional": x.regional, "pdv": x.pdv, "texto": x.texto, "unidades": L["q"],
                      "precio": p, "estado": est, "motivo": L["motivo"]})
    return pd.DataFrame(filas)


def ventas_df(fuente: str = "ambas", mes: str | None = None) -> pd.DataFrame:
    """Ventas del histórico en el formato de VENTA TEÓRICA (lo que usa el informe gerencial), con columna FUENTE.
    Las celdas de Forms en duda no se cuentan hasta que se corrijan."""
    if fuente not in FUENTES:
        raise ErrorArchivo("Fuente de ventas no válida.")
    with _con() as c:
        plat = _plataforma(c)
        fo = _forms(c, plat) if "FORMS" in FUENTES[fuente] else pd.DataFrame()
    partes = []
    if "PLATAFORMA" in FUENTES[fuente] and len(plat):
        partes.append(pd.DataFrame({
            "FECHA_CAPTURA": plat.fecha, "ASESOR": plat.asesor, "ID_ASESOR": plat.id_asesor, "REGIONAL": plat.regional,
            "CIUDAD": plat.ciudad, "SUCURSAL": plat.pdv, "ID_SUCURSAL": plat.id_pdv, "ID_PEDIDO": "P" + plat.pedido,
            "DESCRIPCION_PRODUCTO": plat.sku, "CANTIDAD": plat.unidades, "PRECIO_TOTAL": plat.valor,
            "FUENTE": "Plataforma", "PRECIO_ESTIMADO": False}))
    if len(fo):
        fo = fo[fo.estado != "duda"]
        partes.append(pd.DataFrame({
            "FECHA_CAPTURA": fo.fecha, "ASESOR": fo.asesor, "ID_ASESOR": fo.id_asesor, "REGIONAL": fo.regional,
            "CIUDAD": "", "SUCURSAL": fo.pdv, "ID_SUCURSAL": None, "ID_PEDIDO": "F" + fo.id_resp.astype(str),
            "DESCRIPCION_PRODUCTO": fo.sku, "CANTIDAD": fo.unidades, "PRECIO_TOTAL": fo.unidades * fo.precio.astype(float),
            "FUENTE": "Forms", "PRECIO_ESTIMADO": fo.estado.eq("precio_ref")}))
    if not partes:
        raise ErrorArchivo("El histórico no tiene ventas de esa fuente. Cárgalas en Ventas e histórico.")
    v = pd.concat(partes, ignore_index=True)
    if mes:
        v = v[v.FECHA_CAPTURA.str[:7] == mes]
        if v.empty:
            raise ErrorArchivo(f"No hay ventas guardadas de {mes} en esa fuente.")
    return v


def resumen() -> dict:
    with _con() as c:
        plat = _plataforma(c)
        fo = _forms(c, plat)
        cargas = pd.read_sql("SELECT * FROM cargas ORDER BY cuando DESC LIMIT 10", c)
    meses = {}
    for nom, d, val in (("Plataforma", plat, "valor"), ("Forms", fo, None)):
        if d is None or d.empty:
            continue
        d = d.assign(mes=d.fecha.str[:7])
        if val is None:
            ok = d[d.estado != "duda"]
            g = ok.assign(v=ok.unidades * ok.precio.astype(float)).groupby("mes").agg(
                lineas=("sku", "size"), unidades=("unidades", "sum"), valor=("v", "sum"))
            g["dudas"] = d[d.estado == "duda"].groupby("mes").size()
            g["estimadas"] = d[d.estado == "precio_ref"].groupby("mes").size()
        else:
            g = d.groupby("mes").agg(lineas=("sku", "size"), unidades=("unidades", "sum"), valor=("valor", "sum"))
        g = g.fillna(0)
        for m, x in g.iterrows():
            meses.setdefault(m, {})[nom] = {"lineas": int(x.lineas), "unidades": r(x.unidades, 0), "valor": r(x.valor, 0),
                                            "dudas": int(x.get("dudas", 0)), "estimadas": int(x.get("estimadas", 0))}
    duda = fo[fo.estado == "duda"] if len(fo) else fo
    return {"meses": [{"mes": m, **meses[m]} for m in sorted(meses)],
            "revision": [] if duda is None or duda.empty else duda.sort_values(["fecha", "id_resp"])[
                ["id_resp", "fecha", "asesor", "pdv", "sku", "texto", "motivo", "unidades", "precio"]].astype(object)
            .where(lambda d: d.notna(), None).values.tolist(),
            "registro": cargas.values.tolist(), "carpeta": str(CARPETA)}


def serie_diaria(fuente: str = "ambas") -> pd.Series:
    """Venta diaria en millones. Con dos fuentes se usa solo el periodo en que ambas tienen datos."""
    v = ventas_df(fuente)
    v = v.assign(f=pd.to_datetime(v.FECHA_CAPTURA), m=v.PRECIO_TOTAL.astype(float) / 1e6)
    ini, fin = v.f.min(), v.f.max()
    if fuente == "ambas":
        rangos = v.groupby("FUENTE").f.agg(["min", "max"])
        if len(rangos) == 2:
            ini, fin = rangos["min"].max(), rangos["max"].min()
    s = v[(v.f >= ini) & (v.f <= fin)].groupby("f").m.sum()
    return s.reindex(pd.date_range(ini, fin, freq="D"), fill_value=0.0)
