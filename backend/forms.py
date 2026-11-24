"""Ventas reportadas por el link de Forms (activaciones). La base cruda trae una columna por SKU con texto libre:
'5 precio unidad $48900', '10+$39.400=197000', '$43.300= 1 UNIDAD', '2 (39. 400)', 'No', 'O unidades'.
Aquí se separan cantidad y precio de cada celda.
"""
import re

import pandas as pd

from lectura import ErrorArchivo, fecha, limpio, norm_txt

PRECIO_MIN, PRECIO_MAX = 15_000, 200_000  # rango plausible del precio unitario de un SKU NexGard (pesos)
CANT_MAX = 60  # más unidades de un SKU en una activación se revisa a mano

_CERO = re.compile(r"(NO|N/?A|NINGUN[OA]?|NADA|O|-|\.|X)?")
_CERO_U = re.compile(r"[0O]+\s*(UNIDAD(ES)?|UNIDADS|UNID|UNDS?|UND|UDS?|U)?\.?")


def sku_canon(texto: str) -> str | None:
    """Nombre único de SKU para la plataforma y Forms: 'NEXGARD SPECTRA 7.5   15 KG' y
    'SPECTRA M (7.5-15 KG) TABLETA MASTICABLE' -> 'Spectra 7,5-15 kg'."""
    t = norm_txt(texto).replace("_", " ")
    t = re.sub(r"(\d) (\d)\b", r"\1.\2", t)  # encabezado normalizado: 'COMBO CAT L 2 5 7 5 KG' -> '2.5 7.5'
    if "COMBO" in t:
        return "Combo Cat L" if re.search(r"CAT\s*L\b|2[.,]5\s*-\s*7|0[.,]9", t) else "Combo Cat S"
    n = re.search(r"(\d+(?:[.,]\d+)?)", t[t.find("(") + 1:] if "(" in t else t)
    if not n:
        return None
    x = float(n.group(1).replace(",", "."))
    if "SPECTRA" in t:
        tabla = {2: "2-3,5", 3.5: "3,5-7,5", 7.5: "7,5-15", 15: "15-30", 30: "30-60"}
        return "Spectra " + tabla[min(tabla, key=lambda k: abs(k - x))] + " kg"
    if "NEXGARD" in t or "DOG" in t:
        tabla = {2: "2-4", 4.1: "4,1-10", 10.1: "10,1-25", 25.1: "25,1-50"}
        return "NexGard " + tabla[min(tabla, key=lambda k: abs(k - x))] + " kg"
    return None


def _numeros(s: str):
    s = re.sub(r"(\d)[.,]\s+(\d{3})(?!\d)", r"\1\2", s)  # '39. 400' -> 39400
    while re.search(r"(\d)[.,](\d{3})(?!\d)", s):
        s = re.sub(r"(\d)[.,](\d{3})(?!\d)", r"\1\2", s)  # separador de miles
    return [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", s)]


def leer_celda(texto) -> dict:
    """{'q': unidades, 'p': precio unitario o None, 'estado': cero | ok | sin_precio | duda, 'motivo'}."""
    s = str(texto if texto is not None else "").replace("\xa0", " ").strip().upper()
    if s in ("", "NAN", "NONE") or _CERO.fullmatch(s) or _CERO_U.fullmatch(s):
        return {"q": 0, "p": None, "estado": "cero", "motivo": ""}
    s = re.sub(r"\bO\b(?=\s*UN)", "0", s)
    nums = _numeros(s)
    peq = [n for n in nums if n < 1000]
    din = [n for n in nums if n >= 1000]
    if not peq:
        return {"q": None, "p": din[0] if len(din) == 1 and PRECIO_MIN <= din[0] <= PRECIO_MAX else None,
                "estado": "duda", "motivo": "No se encontró la cantidad"}
    q = peq[0]
    if q == 0:
        return {"q": 0, "p": None, "estado": "cero", "motivo": ""}
    if q != int(q) or q > CANT_MAX:
        return {"q": q, "p": None, "estado": "duda", "motivo": f"Cantidad poco usual ({q:g})"}
    if not din:
        return {"q": q, "p": None, "estado": "sin_precio", "motivo": ""}
    # Precio: un valor en rango de precio unitario; o un total que dividido por la cantidad da un precio plausible.
    for p in din:
        if PRECIO_MIN <= p <= PRECIO_MAX and any(abs(p * q - t) <= 0.03 * t for t in din if t != p):
            return {"q": q, "p": p, "estado": "ok", "motivo": ""}
    unit = [p for p in din if PRECIO_MIN <= p <= PRECIO_MAX]
    if unit:
        return {"q": q, "p": min(unit), "estado": "ok", "motivo": ""}
    tot = [t / q for t in din if PRECIO_MIN <= t / q <= PRECIO_MAX]
    if tot:
        return {"q": q, "p": tot[0], "estado": "ok", "motivo": ""}
    return {"q": q, "p": None, "estado": "duda", "motivo": "Precio fuera de rango"}


def celdas(df: pd.DataFrame) -> pd.DataFrame:
    """Base cruda de Forms (columnas normalizadas) -> una fila por respuesta y SKU con el texto de la celda."""
    col_f = next((c for c in df.columns if c.startswith("FECHA_DE_ACTIVACI")), None)
    col_c = next((c for c in df.columns if c.startswith("CEDULA")), None)
    col_p = next((c for c in df.columns if c.startswith("PDV")), None)
    sku_cols = [c for c in df.columns if not c.startswith(("POINTS", "FEEDBACK")) and sku_canon(c)
                and ("TABLETA" in c or "JERINGA" in c or "DOG" in c or "SPECTRA" in c or "COMBO" in c)]
    if not (col_f and col_c and "ID" in df.columns and sku_cols):
        raise ErrorArchivo("No parece la base cruda de Forms: faltan ID, FECHA DE ACTIVACIÓN, CÉDULA o las columnas de SKU.")
    base = pd.DataFrame({
        "id_resp": pd.to_numeric(df["ID"], errors="coerce"),
        "fecha": fecha(df[col_f]),
        "cedula": df[col_c].map(lambda v: re.sub(r"\.0$", "", limpio(v))),
        "regional": df["REGIONAL"].map(lambda v: limpio(v).upper()) if "REGIONAL" in df else "",
        "pdv": df[col_p].map(limpio) if col_p else "",
    })
    filas = []
    for c in sku_cols:
        filas.append(base.assign(sku=sku_canon(c), texto=df[c].map(lambda v: "" if pd.isna(v) else str(v).strip())))
    out = pd.concat(filas, ignore_index=True).dropna(subset=["id_resp", "fecha"])
    out["id_resp"] = out["id_resp"].astype(int)
    return out
