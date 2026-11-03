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
| Comisiones | Base de ventas | Se calcula en el navegador (sin cambios) |

Acepta `.csv` (separador `;` o `,`, UTF‑8 o Latin‑1) y `.xlsx`. Si un archivo se sube en la casilla equivocada, la API responde qué columnas faltan.

## Reglas de negocio

- En todos los archivos se excluyen las filas que contienen "USUARIO PRUEBA" (usuarios de prueba de la plataforma).

**Encuestas**
- Puntos a cargo: hoja PDVS (el asesor está en la columna rotulada `LATITUD`). El cruce con la encuesta es por `ID PDV` = `ID_SUCURSAL`.
- Herencia por cadena: si el nombre del PdV contiene un nombre de `CADENAS.xlsx` y algún punto de esa cadena fue encuestado en el periodo, el punto queda "Heredado por cadena" y no cuenta como faltante.
- Mensual: solo encuestas del mes elegido (por defecto el último mes del archivo). Universal: todo el histórico; las novedades escritas en la tabla de faltantes descuentan el punto (se guardan en el navegador).
- Precios: se excluyen atípicos fuera de Q1 − 3·RIC y Q3 + 3·RIC (p. ej. un precio de Canilaner digitado con ceros de más).

**Gerencial**
- Cobertura = visitas `EFECTIVA` / total de visitas. Las novedades salen de `ESTADO` en las no efectivas.
- Venta = `PRECIO_TOTAL` de todos los estados de pedido (se muestra el desglose por estado). Fin de semana = vie, sáb y dom.
- % Agotados = agotado / (presente + agotado + no manejante); también se reporta sobre los puntos que manejan el SKU.
- Alertas: líneas de venta con cantidad ≥ 100 y ≥ 20× la mediana del SKU.
- Modelo: regresión lineal con efecto del día de la semana sobre la venta diaria, IC 95 % de la pendiente, pronóstico a 14 días con banda del 95 % y validación en los últimos 14 días (si hay ≥ 28 días). Además: venta por PdV con o sin actividad (Welch) y correlación de Spearman entre agotados y venta por PdV.

## Estructura

```
backend/app.py         API y servidor del frontend
backend/lectura.py     lectura y limpieza (columnas, fechas, números)
backend/encuestas.py   status de encuestas
backend/gerencial.py   indicadores gerenciales
backend/modelo.py      estadística (tendencia, pronóstico, pruebas)
Frontend/              interfaz (un solo HTML)
```

Los datos reales (`gerencial/`, `status encuestas/`, `*.csv`, `*.xlsx`) están en `.gitignore` para no subirlos a GitHub.
