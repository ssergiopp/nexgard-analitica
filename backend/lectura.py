"""Lectura y limpieza de los archivos que exporta la plataforma (CSV con ';' en Latin-1, o Excel)."""
import io
import re
import unicodedata

import numpy as np
import pandas as pd


class ErrorArchivo(ValueError):
    """Error con mensaje listo para mostrar al usuario."""


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_col(c) -> str:
    """'REGIÓN' -> 'REGION', 'ID PV' -> 'ID_PV', 'COLABORADOR(A)' -> 'COLABORADOR_A'."""
    s = sin_tildes(str(c)).upper()
    return re.sub(r"[^A-Z0-9]+", "_", s).strip("_")


def norm_txt(v) -> str:
    """Texto comparable: sin tildes, mayúsculas, espacios simples."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    return re.sub(r"\s+", " ", sin_tildes(str(v))).strip().upper()


def limpio(v) -> str:
    """Texto para mostrar: espacios simples, sin cambiar mayúsculas/tildes."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


_ALIAS_CIUDAD = {"MANIZALEZ": "MANIZALES", "VILLADELROSARIO": "VILLAROSARIO", "CALI": "SANTIAGODECALI",
                 "BOGOTADC": "BOGOTA"}


def ciudad(v) -> str:
    """Clave de ciudad tolerante a la escritura: 'RIO NEGRO' = 'RIONEGRO', 'MANIZALEZ' = 'MANIZALES'."""
    k = re.sub(r"[^A-Z]", "", norm_txt(v))
    return _ALIAS_CIUDAD.get(k, k)


def _csv(data: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            txt = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    primera = txt.split("\n", 1)[0]
    sep = ";" if primera.count(";") >= primera.count(",") else ","
    # index_col=False: algunas filas traen un campo de más (p. ej. =HIPERVINCULO("url";"texto"))
    # y sin esto pandas corre todas las columnas una posición.
    return pd.read_csv(io.StringIO(txt), sep=sep, dtype=str, keep_default_na=False, index_col=False)


def leer(data: bytes, nombre: str, hoja=None) -> pd.DataFrame:
    """Lee CSV o Excel y normaliza nombres de columnas. `hoja`: nombre de hoja preferida (si existe)."""
    if not data:
        raise ErrorArchivo(f"El archivo '{nombre}' está vacío.")
    try:
        if nombre.lower().endswith(".csv"):
            df = _csv(data)
        else:
            libro = pd.read_excel(io.BytesIO(data), sheet_name=None)
            hojas = {norm_col(k): v for k, v in libro.items()}
            df = hojas.get(norm_col(hoja)) if hoja else None
            if df is None:
                df = next(iter(libro.values()))
    except ErrorArchivo:
        raise
    except Exception as e:  # noqa: BLE001
        raise ErrorArchivo(f"No se pudo leer '{nombre}': {e}") from e
    df.columns = [norm_col(c) for c in df.columns]
    df = df.loc[:, [c for c in df.columns if c and not c.startswith("UNNAMED")]]
    return quitar_pruebas(df.dropna(how="all"))


def quitar_pruebas(df: pd.DataFrame) -> pd.DataFrame:
    """Excluye registros de usuarios de prueba de la plataforma (p. ej. 'USUARIO PRUEBA MERCAIMPULSADOR...')."""
    cols = [c for c in df.columns if df[c].dtype == object or pd.api.types.is_string_dtype(df[c])]
    if not cols:
        return df
    prueba = np.zeros(len(df), dtype=bool)
    for c in cols:
        prueba |= df[c].astype(str).str.upper().str.contains("USUARIO PRUEBA", regex=False, na=False).to_numpy()
    return df[~prueba]


def exigir(df: pd.DataFrame, cols, archivo: str):
    falta = [c for c in cols if c not in df.columns]
    if falta:
        raise ErrorArchivo(
            f"Al archivo de {archivo} le faltan columnas: {', '.join(falta)}. "
            "¿Lo subiste en la casilla correcta?"
        )


def num(s: pd.Series) -> pd.Series:
    """Números en formato de la plataforma (49320, '1.234,5', '12,5')."""
    if s.dtype.kind in "if":
        return s.astype(float)

    def f(v):
        t = str(v).strip().replace(" ", "").replace("$", "")
        if not t:
            return np.nan
        if "," in t and "." in t:
            t = t.replace(".", "").replace(",", ".")
        elif "," in t:
            t = t.replace(",", ".")
        try:
            return float(t)
        except ValueError:
            return np.nan

    return s.map(f)


def fecha(s: pd.Series) -> pd.Series:
    """Fechas dd/mm/aaaa, aaaa-mm-dd hh:mm:ss o datetime de Excel. Devuelve solo la fecha (normalizada)."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return s.dt.normalize()
    t = s.astype(str).str.strip()
    iso = t.str.match(r"^\d{4}-\d{2}-\d{2}")
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    out[iso] = pd.to_datetime(t[iso].str[:19], errors="coerce")
    out[~iso] = pd.to_datetime(t[~iso], dayfirst=True, errors="coerce", format="mixed")
    return out.dt.normalize()


def fecha_hora(s: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    return pd.to_datetime(s.astype(str).str.strip(), dayfirst=True, errors="coerce", format="mixed")


def familia(producto) -> str:
    """Familia NexGard a partir del nombre del SKU."""
    p = norm_txt(producto)
    if "SPECTRA" in p:
        return "Spectra"
    if "COMBO" in p:
        return "Combo"
    return "Dog"


def r(v, d=1):
    """Redondeo seguro para JSON (NaN -> None)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else round(f, d)


def pares(serie: pd.Series, d=1, top=None):
    """Serie indexada -> [[etiqueta, valor], ...] ordenada desc."""
    s = serie.sort_values(ascending=False)
    if top:
        s = s.head(top)
    return [[limpio(k) or "(vacío)", r(v, d)] for k, v in s.items()]
