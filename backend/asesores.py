"""Un solo nombre por asesor en todos los archivos.

Cada archivo escribe el nombre distinto (STEFANY / ESTEFANY, JEFFERSON RAMÍREZ / JEFFERSON RAMIREZ GOMEZ),
pero el ID de usuario es el mismo. El nombre oficial es el de la hoja PDVS: para cada ID de usuario se toma
el asesor de PDVS que más se repite entre los puntos que ese usuario registró.
"""
import pandas as pd

from lectura import limpio, num


def nombres(maestro: pd.DataFrame, df: pd.DataFrame, col_usuario: str, col_pdv: str, col_nombre: str) -> pd.Series:
    """Devuelve, fila a fila de `df`, el nombre oficial del asesor (o el del archivo si no se puede cruzar)."""
    dueño = maestro.set_index("id")["asesor"]
    usuario = df[col_usuario].astype(str).str.strip()
    pdv = num(df[col_pdv])
    voto = pd.DataFrame({"u": usuario, "a": pdv.map(dueño)}).dropna()
    oficial = voto.groupby("u")["a"].agg(lambda s: s.mode().iloc[0]) if len(voto) else pd.Series(dtype=str)
    propio = df[col_nombre].map(limpio)
    return usuario.map(oficial).fillna(propio)
