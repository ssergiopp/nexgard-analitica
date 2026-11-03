"""Comisiones por asesor (mercaimpulsador). El backend entrega los indicadores; el pago se calcula en la página
porque depende de la meta, los montos y la calificación de activaciones que se escriben ahí.

  Sell Out   = unidades vendidas (VENTA TEÓRICA) ÷ meta mensual de unidades (igual para todos)
  Cobertura  = visitas efectivas (EFECTIVIDAD_VISITAS) ÷ visitas programadas (suma de FRECUENCIA MES en PDVS)
  Activaciones = calificación manual
  SGI        = días con inicio y fin de jornada (MOMENTOS) ÷ días trabajados
  Pago de cada componente = monto × min(cumplimiento, 100 %)
"""
import pandas as pd

from asesores import nombres
from gerencial import ventas as _ventas_base
from lectura import exigir, fecha, limpio, norm_txt, num, r
from encuestas import _maestro_pdv


def analizar(ventas: pd.DataFrame, cobertura: pd.DataFrame, rutero: pd.DataFrame, momentos: pd.DataFrame):
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

    c = cobertura.assign(_a=nombres(maestro, cobertura, "ID_ASESOR", "ID_PV", "ASESOR"),
                         _ef=cobertura["EFECTIVIDAD"].map(norm_txt) == "EFECTIVA")
    efectivas = c.groupby("_a")["_ef"].sum()

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
            "efectivas": int(e), "programadas": r(p, 0), "pct_cobertura": r(e / p * 100) if p else None,
            "dias": int(d), "jornadas_completas": int(k), "pct_sgi": r(k / d * 100) if d else None,
            "en_maestro": bool(a in prog.index),
        })
    fv = fecha(ventas["FECHA_CAPTURA"]) if "FECHA_CAPTURA" in ventas else pd.Series(dtype="datetime64[ns]")
    periodo = (f"{fv.min():%d/%m/%Y} a {fv.max():%d/%m/%Y}" if fv.notna().any() else "")
    return {"asesores": filas, "periodo_ventas": periodo, "alertas": base["alertas"]}
