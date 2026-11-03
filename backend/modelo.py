"""Modelo estadístico: tendencia lineal con efecto día de la semana, pronóstico con IC 95 %,
validación en datos no vistos, comparación de grupos y correlación."""
import math

import numpy as np
import pandas as pd

from lectura import r

DIAS = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"]  # convención JS getUTCDay()


def _jsdow(fechas: pd.DatetimeIndex):
    return ((fechas.dayofweek + 1) % 7).to_numpy()


def _ajustar(y: np.ndarray, dow: np.ndarray):
    m = len(y)
    t = np.arange(m)
    mt, my = t.mean(), y.mean()
    sxx = ((t - mt) ** 2).sum()
    b = ((t - mt) * (y - my)).sum() / sxx
    a = my - b * mt
    res = y - (a + b * t)
    dm = np.array([res[dow == k].mean() if (dow == k).any() else 0.0 for k in range(7)])
    e = res - dm[dow]
    gl = max(m - 8, 1)
    s = math.sqrt((e ** 2).sum() / gl)
    return {"a": a, "b": b, "dm": dm, "s": s, "se": s / math.sqrt(sxx)}


def _p_normal(z):
    return math.erfc(abs(z) / math.sqrt(2))


def serie_diaria(diaria: pd.Series, horizonte=14):
    diaria = diaria.dropna()
    diaria = diaria[diaria.index.notna()]
    if diaria.empty:
        return None
    idx = pd.date_range(diaria.index.min(), diaria.index.max(), freq="D")
    y = diaria.reindex(idx, fill_value=0).to_numpy(float)
    dow = _jsdow(idx)
    n = len(y)
    out = {"inicio": idx[0].strftime("%Y-%m-%d"), "y": [r(v, 3) for v in y], "n": n,
           "dias_con_venta": int((y > 0).sum()),
           "promedio_dia_semana": [[DIAS[k], r(y[dow == k].mean() if (dow == k).any() else 0, 3)] for k in [1, 2, 3, 4, 5, 6, 0]]}
    if n < 10:
        out["aviso"] = "Muy pocos días para ajustar tendencia y pronóstico (mínimo 10)."
        return out
    M = _ajustar(y, dow)
    out["ajuste"] = {"a": M["a"], "b": M["b"], "dm": M["dm"].tolist(), "s": M["s"], "se": M["se"]}
    z = M["b"] / M["se"] if M["se"] else 0
    out["tendencia"] = {"pendiente": r(M["b"], 4), "ic95": [r(M["b"] - 1.96 * M["se"], 4), r(M["b"] + 1.96 * M["se"], 4)],
                        "p_valor": r(_p_normal(z), 4), "significativa": bool(_p_normal(z) < 0.05)}
    fut = pd.date_range(idx[-1] + pd.Timedelta(days=1), periods=horizonte, freq="D")
    fdow = _jsdow(fut)
    p = M["a"] + M["b"] * np.arange(n, n + horizonte) + M["dm"][fdow]
    out["pronostico"] = {"total": r(p.clip(min=0).sum(), 2),
                         "ic95_total": [r(max(p.sum() - 1.96 * M["s"] * math.sqrt(horizonte), 0), 2),
                                        r(p.sum() + 1.96 * M["s"] * math.sqrt(horizonte), 2)]}
    # Validación: entrenar sin los últimos 14 días y medir error en ellos
    k = 14
    if n >= 28:
        V = _ajustar(y[:-k], dow[:-k])
        tt = np.arange(n - k, n)
        pv = V["a"] + V["b"] * tt + V["dm"][dow[-k:]]
        real = y[-k:]
        err = real - pv
        nz = real > 0
        out["validacion"] = {"dias": k, "rmse": r(math.sqrt((err ** 2).mean()), 3),
                             "mae": r(np.abs(err).mean(), 3),
                             "mape": r((np.abs(err[nz]) / real[nz]).mean() * 100) if nz.any() else None,
                             "cubiertos": int((np.abs(err) <= 1.96 * V["s"]).sum())}
    return out


def comparar_grupos(a: pd.Series, b: pd.Series, na: str, nb: str):
    a, b = a.dropna(), b.dropna()
    if len(a) < 5 or len(b) < 5:
        return {"aviso": "Grupos muy pequeños para comparar (mínimo 5 puntos por grupo).", "n": [len(a), len(b)]}
    d = a.mean() - b.mean()
    se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    p = _p_normal(d / se) if se else 1
    return {"grupos": [[na, int(len(a)), r(a.mean(), 3)], [nb, int(len(b)), r(b.mean(), 3)]],
            "diferencia": r(d, 3), "ic95": [r(d - 1.96 * se, 3), r(d + 1.96 * se, 3)],
            "p_valor": r(p, 4), "significativa": bool(p < 0.05)}


def correlacion(x: pd.Series, y: pd.Series):
    df = pd.concat([x.rename("x"), y.rename("y")], axis=1, join="inner").dropna()
    n = len(df)
    if n < 10:
        return {"aviso": "Menos de 10 puntos de venta en común entre agotados y ventas.", "n": n}
    rp = df.x.corr(df.y)
    rs = df.x.rank().corr(df.y.rank())
    z = math.atanh(max(min(rs, 0.999999), -0.999999)) * math.sqrt(n - 3)
    return {"n": n, "pearson": r(rp, 3), "spearman": r(rs, 3), "p_valor": r(_p_normal(z), 4),
            "significativa": bool(_p_normal(z) < 0.05)}
