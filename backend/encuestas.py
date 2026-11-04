"""Status de encuestas: puntos a cargo vs. encuestados, con herencia por cadena."""
import re

import numpy as np
import pandas as pd

from asesores import nombres
from lectura import ErrorArchivo, ciudad, exigir, fecha, limpio, norm_txt, num, r

COLS_ASESOR = ("COLABORADOR_A", "COLABORADOR", "ASESOR", "MERCAIMPULSADOR")
NUMERICAS = ("NUMERICA",)  # 'Entrada númerica'
CATEGORICAS = ("SI/NO", "LIST", "OPCION MULTIPLE")


def _maestro_pdv(df: pd.DataFrame) -> pd.DataFrame:
    """Hoja PDVS (o RUTERO): un punto por fila con su asesor."""
    exigir(df, ["ID_PDV", "PUNTO_VENTA"], "rutero / PDV")
    col = next((c for c in COLS_ASESOR if c in df.columns), None)
    if col is None:
        # En la hoja PDVS el asesor viene bajo el encabezado 'LATITUD' (mal rotulado):
        # se toma la primera columna de texto después de FRECUENCIA_MES.
        cols = list(df.columns)
        desde = cols.index("FRECUENCIA_MES") + 1 if "FRECUENCIA_MES" in cols else 0
        for c in cols[desde:]:
            v = df[c].dropna().astype(str)
            if len(v) and v.str.contains(r"[A-Za-z]{3,}").mean() > 0.8:
                col = c
                break
    if col is None:
        raise ErrorArchivo("No encontré la columna del asesor (COLABORADOR(A)) en el rutero.")
    m = pd.DataFrame({
        "id": num(df["ID_PDV"]),
        "pdv": df["PUNTO_VENTA"].map(limpio),
        "dir": df["DIRECCION"].map(limpio) if "DIRECCION" in df else "",
        "ciudad": df["CIUDAD"].map(limpio) if "CIUDAD" in df else "",
        "asesor": df[col].map(limpio),
    }).dropna(subset=["id"])
    m["id"] = m["id"].astype("int64")
    return m[m.asesor != ""].drop_duplicates("id")


def _buscador_cadenas(cadenas: pd.DataFrame):
    col = next((c for c in ("PUNTOS_DE_VENTA", "CADENA", "PUNTO_VENTA", "NOMBRE") if c in cadenas), None)
    if col is None:
        raise ErrorArchivo("El archivo de cadenas debe tener la columna 'PUNTOS DE VENTA'.")
    nombres = sorted({norm_txt(x) for x in cadenas[col] if norm_txt(x)}, key=len, reverse=True)
    pats = [(n, re.compile(r"(^|[^A-Z0-9])" + re.escape(n) + r"($|[^A-Z0-9])")) for n in nombres]

    def cadena(nombre_pdv):
        t = norm_txt(nombre_pdv)
        for n, p in pats:
            if p.search(t):
                return n
        return ""

    return cadena


def analizar(cadenas: pd.DataFrame, rutero: pd.DataFrame, enc: pd.DataFrame, periodo: str, mes: str | None,
             asesor: str | None = None):
    """`asesor`: si se indica, todo el resultado (puntos, faltantes, respuestas) es solo de ese asesor."""
    exigir(enc, ["ID_SUCURSAL", "NOMBRE", "FECHA_VISITA", "PREGUNTA", "RESPUESTA"], "encuesta")
    maestro = _maestro_pdv(rutero)
    cadena = _buscador_cadenas(cadenas)

    enc = enc.copy()
    enc["_id"] = num(enc["ID_SUCURSAL"])
    enc["_f"] = fecha(enc["FECHA_VISITA"])
    enc["_mes"] = enc["_f"].dt.strftime("%Y-%m")
    meses = sorted(enc["_mes"].dropna().unique().tolist())
    if periodo == "Mensual":
        mes = mes if mes in meses else (meses[-1] if meses else None)
        enc = enc[enc["_mes"] == mes]
    else:
        mes = None

    visitas = enc.dropna(subset=["_id"]).drop_duplicates("_id")
    encuestados = set(visitas["_id"].astype("int64"))
    # Cadena + ciudad con al menos un punto encuestado. La herencia solo aplica dentro de la misma ciudad.
    ciud_v = visitas["CIUDAD"] if "CIUDAD" in visitas else pd.Series("", index=visitas.index)
    cad_ok = {(c, ciudad(k)) for c, k in zip(visitas["NOMBRE"].map(cadena), ciud_v) if c}

    maestro["cadena"] = maestro["pdv"].map(cadena)
    hereda = [c != "" and (c, ciudad(k)) in cad_ok for c, k in zip(maestro["cadena"], maestro["ciudad"])]
    maestro["estado"] = np.where(
        maestro["id"].isin(encuestados), "Encuestado",
        np.where(hereda, "Heredado por cadena", "Faltante"),
    )

    # PdV encuestados que no están en PDVS: se suman al asesor que hizo la encuesta, con su ciudad.
    fuera = visitas[~visitas["_id"].astype("int64").isin(set(maestro["id"]))]
    if len(fuera):
        # El nombre oficial se deduce con todas las visitas del usuario (los puntos fuera de PDVS no votan).
        quien = (nombres(maestro, visitas, "ID_USUARIO", "ID_SUCURSAL", "ASESOR").loc[fuera.index]
                 if {"ID_USUARIO", "ASESOR"} <= set(fuera.columns) else fuera.get("ASESOR", "").map(limpio))
        extra = pd.DataFrame({
            "id": fuera["_id"].astype("int64"), "pdv": fuera["NOMBRE"].map(limpio), "dir": "",
            "ciudad": fuera["CIUDAD"].map(limpio) if "CIUDAD" in fuera else "", "asesor": quien,
            "cadena": fuera["NOMBRE"].map(cadena), "estado": "Encuestado",
        })
        maestro = pd.concat([maestro, extra], ignore_index=True)

    lista = sorted(maestro["asesor"].dropna().unique().tolist())
    if asesor:
        if asesor not in lista:
            raise ErrorArchivo(f"El asesor '{asesor}' no tiene puntos a cargo en este rutero.")
        # Respuestas del asesor: las que él registró (por ID de usuario) o las de sus puntos a cargo
        suyos = set(maestro.loc[maestro.asesor == asesor, "id"])
        quien = (nombres(maestro, enc, "ID_USUARIO", "ID_SUCURSAL", "ASESOR")
                 if {"ID_USUARIO", "ASESOR"} <= set(enc.columns) else pd.Series("", index=enc.index))
        enc = enc[(quien == asesor) | enc["_id"].isin(suyos)]
        visitas = visitas.loc[visitas.index.isin(enc.index)]
        fuera = fuera.loc[fuera.index.isin(enc.index)]
        maestro = maestro[maestro.asesor == asesor]

    g = maestro.groupby("asesor")
    asesores = [{
        "asesor": a,
        "a_cargo": int(len(d)),
        "encuestados": int((d.estado == "Encuestado").sum()),
        "heredados": int((d.estado == "Heredado por cadena").sum()),
        "con_cadenas": int((d.estado != "Faltante").sum()),
        "faltantes": int((d.estado == "Faltante").sum()),
    } for a, d in g]
    asesores.sort(key=lambda x: (-x["faltantes"], x["asesor"]))

    falt = maestro[maestro.estado == "Faltante"].sort_values(["asesor", "pdv"])
    faltantes = [{"id": int(x.id), "pdv": x.pdv, "asesor": x.asesor, "dir": x.dir, "ciudad": x.ciudad}
                 for x in falt.itertuples()]

    total = len(maestro)
    cubiertos = int((maestro.estado != "Faltante").sum())
    resumen = {
        "periodo": periodo, "mes": mes, "meses": meses,
        "encuesta": limpio(enc["NOMBRE_ENCUESTA"].iloc[0]) if "NOMBRE_ENCUESTA" in enc and len(enc) else "",
        "puntos": total, "encuestados": int((maestro.estado == "Encuestado").sum()),
        "heredados": int((maestro.estado == "Heredado por cadena").sum()),
        "faltantes": total - cubiertos, "avance": r(cubiertos / total * 100 if total else 0),
        "fuera_maestro": int(len(fuera)),
        "fuera_maestro_lista": [limpio(x) for x in fuera["NOMBRE"].head(50)],
        "asesor": asesor,
    }
    return {"resumen": resumen, "asesores": asesores, "faltantes": faltantes,
            "preguntas": _preguntas(enc), "semanas": _semanas(visitas), "lista_asesores": lista}


def _preguntas(enc: pd.DataFrame):
    out = []
    tipo_col = "TIPO_PREGUNTA" if "TIPO_PREGUNTA" in enc else None
    for preg, d in enc.groupby("PREGUNTA", sort=False):
        tipo = norm_txt(d[tipo_col].iloc[0]) if tipo_col else ""
        resp = d["RESPUESTA"]
        if any(k in tipo for k in NUMERICAS):
            v0 = num(resp).dropna()
            v0 = v0[v0 > 0]
            if len(v0) == 0:
                continue
            # Atípicos (errores de digitación): fuera de Q1 - 3·RIC o Q3 + 3·RIC
            q1, q3 = v0.quantile([0.25, 0.75])
            lo, hi = q1 - 3 * (q3 - q1), q3 + 3 * (q3 - q1)
            v = v0[(v0 >= lo) & (v0 <= hi)]
            resp = resp.where(num(resp).between(lo, hi))
            sd = v.std(ddof=1) if len(v) > 1 else 0
            ic = 1.96 * sd / np.sqrt(len(v)) if len(v) > 1 else 0
            reg = {}
            if "REGIONAL" in d:
                dd = d.assign(_v=num(resp)).query("_v > 0")
                reg = dd.groupby(dd["REGIONAL"].map(limpio))["_v"].mean().round(0).to_dict()
            out.append({"pregunta": limpio(preg), "tipo": "numerica", "n": int(len(v)), "atipicos": int(len(v0) - len(v)),
                        "media": r(v.mean(), 0), "mediana": r(v.median(), 0), "min": r(v.min(), 0),
                        "max": r(v.max(), 0), "de": r(sd, 0), "ic95": [r(v.mean() - ic, 0), r(v.mean() + ic, 0)],
                        "cv": r(sd / v.mean() * 100 if v.mean() else None), "por_regional": reg})
        elif any(k in tipo for k in CATEGORICAS):
            vals = resp.map(limpio)
            vals = vals[vals != ""]
            if len(vals) == 0:
                continue
            c = vals.map(norm_txt).value_counts()
            etiqueta = {norm_txt(x): x for x in vals}
            out.append({"pregunta": limpio(preg), "tipo": "categorica", "n": int(len(vals)),
                        "opciones": [[etiqueta[k].upper(), int(n), r(n / len(vals) * 100)] for k, n in c.head(12).items()]})
        else:
            out.append({"pregunta": limpio(preg), "tipo": "otra", "n": int((resp.map(limpio) != "").sum())})
    return out


def _semanas(visitas: pd.DataFrame):
    v = visitas.dropna(subset=["_f"])
    if v.empty:
        return []
    s = v.groupby(v["_f"].dt.to_period("W-SUN").dt.start_time).size()
    return [[k.strftime("%d/%m"), int(n)] for k, n in s.items()]
