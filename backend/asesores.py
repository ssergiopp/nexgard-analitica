"""Un solo nombre por asesor en todos los archivos.

Cada archivo escribe el nombre distinto (STEFANY / ESTEFANY, STEPHANNY RODRIGUEZ / STHEPANY RODRIGUEZ MONTOYA,
JEFFERSON RAMÍREZ / JEFFERSON RAMIREZ GOMEZ). Se unifica en dos pasos:
1. Por ID de usuario: se toma el asesor de la hoja PDVS que más se repite entre los puntos que ese usuario registró.
2. Por similitud del nombre: dos nombres son la misma persona si el primer nombre suena igual (STEPHANNY ≈ STHEPANY ≈
   STEPPANY) y comparten al menos un apellido. Se deja el nombre de la hoja PDVS (o el más frecuente si no está ahí).
"""
import re
from difflib import SequenceMatcher

import pandas as pd

from lectura import limpio, num, sin_tildes


def _fon(token: str) -> str:
    """Clave fonética simple del español para comparar nombres mal escritos."""
    t = re.sub(r"[^A-Z]", "", sin_tildes(token).upper())
    t = t.replace("PH", "F").replace("TH", "T").replace("CH", "X").replace("H", "")
    t = t.translate(str.maketrans("YZVK", "ISBC"))
    t = re.sub(r"(.)\1+", r"\1", t)  # letras dobles: STEPPANY -> STEPANI
    return re.sub(r"^ES(?=[^AEIOU])", "S", t)  # ESTEFANY -> STEFANI


def _tokens(nombre: str):
    return [x for x in (_fon(p) for p in str(nombre).split()) if x]


def _parecido(a: str, b: str, umbral: float) -> bool:
    return a == b or SequenceMatcher(None, a, b).ratio() >= umbral


def mismo(a: str, b: str) -> bool:
    """¿Los dos nombres son de la misma persona? Primer nombre parecido y al menos un apellido en común."""
    ta, tb = _tokens(a), _tokens(b)
    if len(ta) < 2 or len(tb) < 2 or not _parecido(ta[0], tb[0], 0.8):
        return False
    return any(_parecido(x, y, 0.85) for x in ta[1:] if len(x) >= 4 for y in tb[1:] if len(y) >= 4)


def agrupar(conteo: dict, preferidos=()) -> dict:
    """{nombre: veces} -> {nombre: nombre estándar}. El estándar es un nombre de `preferidos` (hoja PDVS) si el grupo
    tiene alguno; si no, el más frecuente."""
    nombres = [n for n in conteo if n]
    padre = {n: n for n in nombres}

    def raiz(n):
        while padre[n] != n:
            padre[n] = padre[padre[n]]
            n = padre[n]
        return n

    for i, a in enumerate(nombres):
        for b in nombres[i + 1:]:
            if raiz(a) != raiz(b) and mismo(a, b):
                padre[raiz(a)] = raiz(b)
    grupos = {}
    for n in nombres:
        grupos.setdefault(raiz(n), []).append(n)
    pref = set(preferidos)
    out = {}
    for g in grupos.values():
        estandar = max(g, key=lambda n: (n in pref, conteo[n], len(n)))
        out.update({n: estandar for n in g})
    return out


def estandarizar(s: pd.Series, preferidos=()) -> pd.Series:
    """Reemplaza cada nombre por su nombre estándar (ver `agrupar`)."""
    s = s.map(limpio)
    return s.map(agrupar(s[s != ""].value_counts().to_dict(), preferidos)).fillna(s)


def nombres(maestro: pd.DataFrame, df: pd.DataFrame, col_usuario: str, col_pdv: str, col_nombre: str) -> pd.Series:
    """Devuelve, fila a fila de `df`, el nombre oficial del asesor (o el del archivo si no se puede cruzar)."""
    dueño = maestro.set_index("id")["asesor"]
    usuario = df[col_usuario].astype(str).str.strip()
    pdv = num(df[col_pdv])
    voto = pd.DataFrame({"u": usuario, "a": pdv.map(dueño)}).dropna()
    oficial = voto.groupby("u")["a"].agg(lambda s: s.mode().iloc[0]) if len(voto) else pd.Series(dtype=str)
    propio = df[col_nombre].map(limpio)
    res = usuario.map(oficial).fillna(propio)
    # Los nombres que no se pudieron cruzar por ID se emparejan por similitud con los de la hoja PDVS.
    oficiales = maestro["asesor"].unique()
    conteo = res[res != ""].value_counts().to_dict()
    conteo.update({n: conteo.get(n, 0) for n in oficiales})
    return res.map(agrupar(conteo, oficiales)).fillna(res)
