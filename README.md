# Plataforma analítica NexGard (Eficacia × Boehringer Ingelheim)

Aplicación local: el navegador sube los archivos que exporta la plataforma de campo, el backend (Python/FastAPI) los procesa **en memoria y los descarta**. No hay base de datos ni usuarios.

## Cómo correrla (Windows)

1. Instala Python 3.10 o superior (marca "Add to PATH").
2. Doble clic en `iniciar.bat`. La primera vez crea `.venv` e instala dependencias; luego abre http://localhost:8000.

Manual: `python -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt`, `.venv\Scripts\python -m uvicorn app:app --app-dir backend --port 8000`.

> La página debe abrirse desde `http://localhost:8000`, no con doble clic al `.html`.

## Módulos y archivos

| Módulo | Archivos | Endpoint |
|---|---|---|
| Encuestas | `CADENAS.xlsx`, `plan de trabajo y pdv.xlsx` (hoja **PDVS**), una encuesta (`precios`, `distribuidores`, `atrevia y canilaner`) | `POST /api/encuestas` |
| Gerencial | `VENTA TEORICA`, `AGOTADOS`, `EFECTIVIDAD_VISITAS` (cobertura), `MOMENTOS`, `ACTIVIDADES`, `OBSEQUIOS` | `POST /api/gerencial` |
| Comisiones | `VENTA TEORICA`, `EFECTIVIDAD_VISITAS`, `plan de trabajo y pdv.xlsx` (hoja PDVS), `MOMENTOS` | `POST /api/comisiones` |
| Ventas y pronóstico | `VENTA TEORICA` (uno o varios meses) y la base cruda de Forms; quedan guardadas en `datos/` | `/api/historico/*`, `POST /api/pronostico` |

Acepta `.csv` (separador `;` o `,`, UTF‑8 o Latin‑1) y `.xlsx`. Si un archivo se sube en la casilla equivocada, la API responde qué columnas faltan.

## Reglas de negocio

- En todos los archivos se excluyen las filas que contienen "USUARIO PRUEBA" (usuarios de prueba de la plataforma).

**Encuestas**
- Puntos a cargo: hoja PDVS (el asesor está en la columna rotulada `LATITUD`). El cruce con la encuesta es por `ID PDV` = `ID_SUCURSAL`.
- Herencia por cadena: si el nombre del PdV contiene un nombre de `CADENAS.xlsx` y otro punto de esa cadena fue encuestado en el periodo, el punto queda "Heredado por cadena" (no cuenta como faltante) cuando ese otro punto es **del mismo asesor (en cualquier ciudad)** o **de la misma ciudad (de cualquier asesor)**. Si el punto tiene su propia encuesta, cuenta como encuestado. Las ciudades se comparan sin tildes ni espacios (RIO NEGRO = RIONEGRO, MANIZALEZ = MANIZALES).
- PdV encuestados que no están en PDVS se suman como puntos encuestados del asesor que hizo la encuesta.
- Vincular (manual): en un faltante, "Vincular" abre un buscador de las encuestas del periodo; al elegir una, el faltante pasa a encuestado. Si la encuesta era de un punto fuera de PDVS, pasa a ser del faltante (no se cuenta dos veces); si es de otro punto del maestro, ese punto la conserva. Los vínculos se guardan en el navegador y se pueden quitar.
- Mensual: solo encuestas del mes elegido (por defecto el último mes del archivo). Universal: todo el histórico; las novedades escritas en la tabla de faltantes descuentan el punto (se guardan en el navegador).
- Precios: se excluyen atípicos fuera de Q1 − 3·RIC y Q3 + 3·RIC (p. ej. un precio de Canilaner digitado con ceros de más).

**Gerencial**
- Cobertura = visitas `EFECTIVA` / total de visitas. Las novedades salen de `ESTADO` en las no efectivas.
- Venta = `PRECIO_TOTAL` de todos los estados de pedido (se muestra el desglose por estado). Fin de semana = vie, sáb y dom.
- % Agotados = agotado / (presente + agotado + no manejante); también se reporta sobre los puntos que manejan el SKU.
- Líneas de venta con cantidad ≥ 100 y ≥ 20× la mediana del SKU se excluyen (error de digitación) y se muestran como alerta.
- Modelo: regresión lineal con efecto del día de la semana sobre la venta diaria, IC 95 % de la pendiente, pronóstico a 14 días con banda del 95 % y validación en los últimos 14 días (si hay ≥ 28 días). Además: venta por PdV con o sin actividad (Welch) y correlación de Spearman entre agotados y venta por PdV.

**Asesores**
- Cada archivo escribe el nombre distinto (STEFANY / ESTEFANY). Se usa el nombre de la hoja PDVS, cruzando por el ID de usuario y los puntos que registró.
- Si no se puede cruzar por ID, se une por similitud del nombre: el primer nombre suena igual (STEPHANNY ≈ STHEPANY ≈ STEPPANY) y comparten al menos un apellido. Queda el nombre de la hoja PDVS o, si no está ahí, el más frecuente. En Gerencial, un asesor con varios usuarios aparece una sola vez en el selector.

**Comisiones** (máximo $200.000 por asesor; montos editables en la página)

| Componente | Monto | Cumplimiento |
|---|---|---|
| Sell Out | $50.000 | Unidades de VENTA TEÓRICA ÷ meta mensual de unidades (igual para todos) |
| Cobertura – cumplimiento ruta | $80.000 | Visitas efectivas ÷ suma de FRECUENCIA MES de los PdV a cargo |
| Activaciones | $20.000 | Calificación manual (0–100 %), guardada en el navegador |
| SGI | $50.000 | Días con inicio y fin de jornada (MOMENTOS) ÷ días trabajados |

Pago de cada componente = monto × cumplimiento, con tope del 100 %.

Al hacer clic en el % de Cobertura de un asesor (o en "Motivos de cobertura" para todos) se abre el desglose de visitas efectivas y no efectivas por motivo (columna `ESTADO` de EFECTIVIDAD_VISITAS).

**Ventas y pronóstico** (histórico guardado en este PC)
- El histórico vive en `datos/historico.sqlite` (excluido de GitHub). Se puede cambiar la carpeta con la variable de entorno `NEXGARD_DATOS`, por ejemplo a una carpeta de OneDrive para tener respaldo.
- Plataforma: de cada archivo de VENTA TEÓRICA se usa la hoja de pedidos; se ignoran `VENTAS FIN DE SEMANA` (repite pedidos) e `HISTORICO` (es de otro año). Cada línea se identifica por pedido, producto, cantidad y valor: subir el mismo archivo dos veces no duplica ventas.
- Forms: se sube la base cruda completa del link y reemplaza la anterior. Las ventas de Forms son **adicionales** a las de la plataforma. Cada celda de SKU es texto libre ("5 precio unidad $48900", "10+$39.400=197000"): se separan cantidad y precio; si hay precio y total y cantidad × precio no da el total escrito, la celda va a revisión; si no hay precio se usa la mediana del SKU en la plataforma ese mes (marcado como precio estimado). Las celdas dudosas no se cuentan hasta corregirlas en la tabla de revisión; la corrección se conserva al volver a subir la base.
- Los SKU se unifican entre fuentes (p. ej. `NEXGARD SPECTRA 7.5 15 KG` y `SPECTRA M (7.5-15 KG)` = `Spectra 7,5-15 kg`). La cédula de Forms se nombra con la hoja FORM de VENTA TEÓRICA.
- Gerencial puede tomar las ventas del histórico (plataforma, Forms o ambas; mensual o universal) en lugar del archivo subido.
- Pronóstico de la venta diaria (con ambas fuentes, solo el periodo en que las dos tienen datos; se aplica la misma regla de cantidades atípicas del informe gerencial):
  - Box-Jenkins: ADF y KPSS (se diferencia solo si ambas indican no estacionariedad), ACF/PACF, SARIMA(p,d,q)(P,D,Q)7 por AIC restringido a la región estacionaria e invertible, Ljung-Box y Jarque-Bera de residuos.
  - Modelos comparados: ingenuo estacional y promedio móvil 7 días (referencia), regresión con día de la semana, Holt-Winters, SARIMA, bagging, random forest y XGBoost (rezagos 1, 7, 14, media móvil y calendario; pronóstico recursivo).
  - Validación de origen móvil (hasta 4 cortes de `horizonte` días); RMSE, MAE y MAPE; prueba de Diebold-Mariano (corrección HLN) de cada modelo contra el mejor; sesgo (error medio), correlación real vs. pronóstico y Durbin-Watson de los errores; prueba de Friedman sobre el error absoluto (mediciones pareadas por día) con post hoc de Wilcoxon y Bonferroni, y Shapiro-Wilk del error del mejor modelo. El pronóstico final usa el de menor RMSE, con banda del 95 % según el error de validación.

## Estructura

```
backend/app.py         API y servidor del frontend
backend/lectura.py     lectura y limpieza (columnas, fechas, números)
backend/encuestas.py   status de encuestas
backend/gerencial.py   indicadores gerenciales
backend/modelo.py      estadística (tendencia, pronóstico, pruebas)
backend/comisiones.py  indicadores de comisiones
backend/asesores.py    nombre único de asesor entre archivos
backend/historico.py   histórico de ventas (SQLite): plataforma + Forms
backend/forms.py       lectura de la base cruda de Forms (cantidad y precio desde el texto)
backend/pronostico.py  Box-Jenkins, SARIMA, modelos clásicos y de aprendizaje automático
Frontend/              interfaz (un solo HTML)
```

Los datos reales (`gerencial/`, `status encuestas/`, `*.csv`, `*.xlsx`) están en `.gitignore` para no subirlos a GitHub.
