"""Pronóstico de la venta diaria: metodología Box-Jenkins (SARIMA), modelos clásicos y de aprendizaje automático,
comparados con validación de origen móvil y la prueba de Diebold-Mariano.

Modelos:
  Referencia: ingenuo estacional (misma venta de hace 7 días) y promedio móvil de 7 días.
  Clásicos:   regresión con tendencia y día de la semana; Holt-Winters (suavizamiento exponencial, estacionalidad 7).
  Box-Jenkins: SARIMA(p,d,q)(P,D,Q)7 elegido por AIC tras las pruebas de estacionariedad.
  Aprendizaje automático: bagging de árboles, random forest y XGBoost con rezagos y calendario (pronóstico recursivo).
"""
import math
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import BaggingRegressor, RandomForestRegressor
from sklearn.tree import DecisionTreeRegressor
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.stattools import acf, adfuller, kpss, pacf
from xgboost import XGBRegressor

from lectura import r
from modelo import serie_diaria as tendencia_base

S = 7  # estacionalidad semanal
warnings.filterwarnings("ignore")


# ---------- Modelos: cada uno recibe la serie de entrenamiento y el horizonte, devuelve el pronóstico ----------
def _ingenuo(y, h):
    return np.array([y[len(y) - S + (i % S)] for i in range(h)])


def _media_movil(y, h):
    return np.full(h, y[-S:].mean())


def _regresion(y, h):
    n, t = len(y), np.arange(len(y))
    X = np.column_stack([np.ones(n), t] + [(t % S == k).astype(float) for k in range(1, S)])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    tf = np.arange(n, n + h)
    Xf = np.column_stack([np.ones(h), tf] + [(tf % S == k).astype(float) for k in range(1, S)])
    return Xf @ b


def _holt_winters(y, h):
    m = ExponentialSmoothing(y, trend="add", damped_trend=True, seasonal="add", seasonal_periods=S,
                             initialization_method="estimated").fit()
    return m.forecast(h)


def _sarima_fit(y, orden, sorden):
    # Box-Jenkins exige un modelo estacionario e invertible: se restringe la estimación a esa región.
    return SARIMAX(y, order=orden, seasonal_order=sorden + (S,), enforce_stationarity=True,
                   enforce_invertibility=True).fit(disp=False)


def _features(hist, t):
    """Variables para el día t a partir de la historia (real + pronosticada): rezagos, media móvil y calendario."""
    dow = [1.0 if t % S == k else 0.0 for k in range(S)]
    return [t, hist[t - 1], hist[t - S], hist[t - 2 * S], np.mean(hist[t - S:t])] + dow


def _ml(modelo):
    def f(y, h):
        y = list(y)
        X = [_features(y, t) for t in range(2 * S, len(y))]
        m = modelo()
        m.fit(np.array(X), np.array(y[2 * S:]))
        hist = y[:]
        for _ in range(h):  # recursivo: cada pronóstico entra como rezago del siguiente día
            hist.append(float(m.predict(np.array([_features(hist, len(hist))]))[0]))
        return np.array(hist[len(y):])
    return f


MODELOS = {
    "Ingenuo estacional (referencia)": ("Referencia", _ingenuo),
    "Promedio móvil 7 días (referencia)": ("Referencia", _media_movil),
    "Regresión: tendencia + día de la semana": ("Clásico", _regresion),
    "Holt-Winters": ("Clásico", _holt_winters),
    "SARIMA (Box-Jenkins)": ("Box-Jenkins", None),  # usa el orden elegido
    "Bagging (árboles)": ("Aprendizaje automático",
                          _ml(lambda: BaggingRegressor(DecisionTreeRegressor(min_samples_leaf=3), n_estimators=200,
                                                       random_state=1))),
    "Random forest": ("Aprendizaje automático",
                      _ml(lambda: RandomForestRegressor(n_estimators=300, min_samples_leaf=3, max_features="sqrt", random_state=1))),
    "XGBoost": ("Aprendizaje automático",
                _ml(lambda: XGBRegressor(n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8,
                                         random_state=1, verbosity=0))),
}


# ---------- Box-Jenkins ----------
def box_jenkins(y: np.ndarray) -> dict:
    """Identificación (ADF, KPSS, ACF/PACF), estimación por AIC y diagnóstico de residuos."""
    n = len(y)
    adf = adfuller(y, autolag="AIC")
    try:
        kp = kpss(y, regression="c", nlags="auto")
    except Exception:  # noqa: BLE001
        kp = (np.nan, np.nan)
    # Se diferencia solo si las dos pruebas coinciden en que no es estacionaria (ADF no rechaza raíz unitaria y KPSS
    # rechaza estacionariedad); así se evita sobrediferenciar (síntoma: MA(1) cercano a −1).
    d = 1 if adf[1] >= 0.05 and np.isfinite(kp[1]) and kp[1] < 0.05 else 0
    adf_d = adfuller(np.diff(y), autolag="AIC") if d else None
    # Diferencia estacional solo si la venta de cada día de la semana no es estacionaria (ADF sobre y_t - y_{t-7})
    D = 0
    nl = min(21, n // 2 - 1)
    serie_ident = np.diff(y) if d else y
    acf_v, acf_ci = acf(serie_ident, nlags=nl, alpha=0.05)
    pacf_v = pacf(serie_ident, nlags=nl, method="ywm")
    lim = 1.96 / math.sqrt(len(serie_ident))
    cands = []
    for p in range(3):
        for q in range(3):
            for P in range(2):
                for Q in range(2):
                    try:
                        m = _sarima_fit(y, (p, d, q), (P, D, Q))
                        if np.isfinite(m.aic):
                            cands.append(((p, d, q), (P, D, Q), m.aic, m))
                    except Exception:  # noqa: BLE001
                        pass
    cands.sort(key=lambda c: c[2])
    orden, sorden, aic, m = cands[0]
    res = m.resid[max(d, 1) + S:]
    lb = acorr_ljungbox(res, lags=[7, 14], return_df=True)
    jb = stats.jarque_bera(res)
    coef = [[k, r(v, 4), r(se, 4), r(pv, 4)] for k, v, se, pv in zip(m.param_names, m.params, m.bse, m.pvalues)
            if k != "sigma2"]
    return {
        "n": n,
        "adf": {"estadistico": r(adf[0], 3), "p": r(adf[1], 4), "estacionaria": bool(adf[1] < 0.05)},
        "adf_diferenciada": {"estadistico": r(adf_d[0], 3), "p": r(adf_d[1], 4)} if adf_d else None,
        "kpss": {"estadistico": r(kp[0], 3), "p": r(kp[1], 4)} if np.isfinite(kp[0]) else None,
        "d": d, "D": D,
        "acf": [r(v, 3) for v in acf_v[1:]], "pacf": [r(v, 3) for v in pacf_v[1:]], "limite": r(lim, 3),
        "orden": list(orden), "orden_estacional": list(sorden) + [S], "aic": r(aic, 1), "bic": r(m.bic, 1),
        "candidatos": [[list(c[0]), list(c[1]) + [S], r(c[2], 1)] for c in cands[:5]],
        "coeficientes": coef,
        "ljung_box": [[int(l), r(float(lb.loc[l, "lb_stat"]), 2), r(float(lb.loc[l, "lb_pvalue"]), 4)] for l in lb.index],
        "jarque_bera": {"estadistico": r(float(jb.statistic), 2), "p": r(float(jb.pvalue), 4)},
        "_modelo": m, "_orden": orden, "_sorden": sorden,
    }


# ---------- Comparación ----------
def _dm(e1, e2, h):
    """Diebold-Mariano (pérdida cuadrática) con la corrección de Harvey, Leybourne y Newbold. p bilateral."""
    dlt = e1 ** 2 - e2 ** 2
    n = len(dlt)
    if n < 5 or np.allclose(dlt, 0):
        return None
    g = [np.mean((dlt[k:] - dlt.mean()) * (dlt[:n - k] - dlt.mean())) for k in range(h)]
    var = (g[0] + 2 * sum(g[1:])) / n
    if var <= 0:  # autocovarianzas que dan varianza negativa: se usa solo la varianza
        var = g[0] / n
    if var <= 0:
        return None
    dm = dlt.mean() / math.sqrt(var) * math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    return float(2 * stats.t.sf(abs(dm), n - 1))


def _metricas(real, pred):
    e = real - pred
    nz = real > 0
    return {"rmse": r(math.sqrt(np.mean(e ** 2)), 3), "mae": r(np.mean(np.abs(e)), 3),
            "mape": r(np.mean(np.abs(e[nz]) / real[nz]) * 100, 1) if nz.any() else None}


def analizar(serie: pd.Series, horizonte: int = 14, fuente: str = "ambas") -> dict:
    y = serie.to_numpy(float)
    n = len(y)
    fechas = [d.strftime("%Y-%m-%d") for d in serie.index]
    if n < 6 * S:
        return {"aviso": f"Hay {n} días en el histórico; se necesitan al menos {6 * S} para el pronóstico.",
                "fechas": fechas, "y": [r(v, 3) for v in y]}
    bj = box_jenkins(y)
    orden, sorden = bj.pop("_orden"), bj.pop("_sorden")
    m_full = bj.pop("_modelo")
    MODELOS["SARIMA (Box-Jenkins)"] = ("Box-Jenkins", lambda yy, hh: _sarima_fit(yy, orden, sorden).forecast(hh))

    # Validación de origen móvil: varios cortes; en cada uno se entrena con lo anterior y se pronostica `horizonte` días.
    pliegues = max(1, min(4, (n - 8 * S) // horizonte))
    cortes = [n - horizonte * (k + 1) for k in range(pliegues)][::-1]
    real = np.concatenate([y[c:c + horizonte] for c in cortes])
    errores, tabla = {}, []
    for nombre, (familia, f) in MODELOS.items():
        try:
            pred = np.concatenate([np.asarray(f(y[:c], horizonte), float) for c in cortes])
        except Exception as e:  # noqa: BLE001
            tabla.append({"modelo": nombre, "familia": familia, "error": str(e)[:120]})
            continue
        errores[nombre] = real - pred
        tabla.append({"modelo": nombre, "familia": familia, **_metricas(real, pred)})
    ok = [t for t in tabla if "rmse" in t]
    ok.sort(key=lambda t: t["rmse"])
    mejor = ok[0]["modelo"]
    for i, t in enumerate(ok):
        t["puesto"] = i + 1
        t["dm_p"] = None if t["modelo"] == mejor else r(_dm(errores[t["modelo"]], errores[mejor], horizonte), 4)
    ref = min((t for t in ok if t["familia"] == "Referencia"), key=lambda t: t["rmse"])
    for t in ok:
        t["mejora_vs_referencia"] = r((1 - t["rmse"] / ref["rmse"]) * 100, 1) if ref["rmse"] else None

    # Pronóstico final: el mejor modelo con toda la serie; banda con el error de la validación.
    fut = pd.date_range(serie.index[-1] + pd.Timedelta(days=1), periods=horizonte, freq="D")
    p_mejor = np.asarray(MODELOS[mejor][1](y, horizonte), float).clip(min=0)
    sd = float(np.std(errores[mejor], ddof=1))
    fc = m_full.get_forecast(horizonte)
    ci = np.asarray(fc.conf_int(alpha=0.05))
    tend = tendencia_base(serie)
    return {
        "fuente": fuente, "fechas": fechas, "y": [r(v, 3) for v in y], "n": n,
        "desde": fechas[0], "hasta": fechas[-1], "horizonte": horizonte,
        "box_jenkins": bj,
        "validacion": {"pliegues": pliegues, "dias_evaluados": int(len(real)), "cortes": [fechas[c] for c in cortes]},
        "comparacion": ok + [t for t in tabla if "error" in t],
        "mejor": mejor, "referencia": ref["modelo"],
        "pronostico": {"fechas": [d.strftime("%Y-%m-%d") for d in fut], "modelo": mejor,
                       "valor": [r(v, 3) for v in p_mejor],
                       "lo": [r(max(v - 1.96 * sd, 0), 3) for v in p_mejor],
                       "hi": [r(v + 1.96 * sd, 3) for v in p_mejor], "total": r(p_mejor.sum(), 2)},
        "pronostico_sarima": {"valor": [r(max(v, 0), 3) for v in np.asarray(fc.predicted_mean)],
                              "lo": [r(max(v, 0), 3) for v in ci[:, 0]], "hi": [r(v, 3) for v in ci[:, 1]],
                              "total": r(np.asarray(fc.predicted_mean).clip(min=0).sum(), 2)},
        "tendencia": tend.get("tendencia"),
        "promedio_dia_semana": tend.get("promedio_dia_semana"),
    }
