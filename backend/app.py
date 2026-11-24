"""API de la plataforma analítica NexGard. Procesa los archivos en memoria y los descarta.

Ejecutar desde la carpeta del proyecto:  python -m uvicorn app:app --app-dir backend --port 8000
"""
import json
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import comisiones
import encuestas
import gerencial
import historico
import pronostico
from lectura import ErrorArchivo, leer, leer_hojas

RAIZ = Path(__file__).resolve().parent.parent
FRONT = RAIZ / "Frontend" / "Aplicativo de Eficacia NexGard.html"
MAX_MB = 60

app = FastAPI(title="Plataforma analítica NexGard")


@app.exception_handler(ErrorArchivo)
async def _error_archivo(_, exc: ErrorArchivo):
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(Exception)
async def _error(_, exc: Exception):
    return JSONResponse(status_code=500, content={"error": f"Error procesando los datos: {exc}"})


async def _leer(f: UploadFile, hoja=None):
    data = await f.read()
    if len(data) > MAX_MB * 1024 * 1024:
        raise ErrorArchivo(f"'{f.filename}' supera {MAX_MB} MB.")
    return leer(data, f.filename or "archivo", hoja)


def _json(texto):
    """Lee un JSON enviado como campo de formulario; si no es válido, se ignora."""
    if not texto:
        return None
    try:
        v = json.loads(texto)
        return v if isinstance(v, dict) else None
    except ValueError:
        return None


@app.get("/")
def inicio():
    return FileResponse(FRONT)


@app.get("/api/salud")
def salud():
    return {"ok": True}


@app.post("/api/encuestas")
async def api_encuestas(
    cadenas: UploadFile = File(...), rutero: UploadFile = File(...), encuesta: UploadFile = File(...),
    periodo: str = Form("Mensual"), mes: str | None = Form(None), asesor: str | None = Form(None),
    vinculos: str | None = Form(None),
):
    if periodo not in ("Mensual", "Universal"):
        raise ErrorArchivo("El periodo debe ser Mensual o Universal.")
    return encuestas.analizar(await _leer(cadenas), await _leer(rutero, "PDVS"), await _leer(encuesta), periodo, mes, asesor or None,
                              _json(vinculos))


@app.post("/api/comisiones")
async def api_comisiones(
    ventas: UploadFile = File(...), cobertura: UploadFile = File(...),
    rutero: UploadFile = File(...), momentos: UploadFile = File(...),
):
    return comisiones.analizar(await _leer(ventas), await _leer(cobertura), await _leer(rutero, "PDVS"),
                               await _leer(momentos))


@app.post("/api/gerencial")
async def api_gerencial(
    ventas: UploadFile | None = File(None), agotados: UploadFile | None = File(None),
    cobertura: UploadFile | None = File(None), momentos: UploadFile | None = File(None),
    actividades: UploadFile | None = File(None), obsequios: UploadFile | None = File(None),
    asesor: str | None = Form(None), ventas_fuente: str | None = Form(None), ventas_mes: str | None = Form(None),
):
    subidos = dict(ventas=ventas, agotados=agotados, cobertura=cobertura, momentos=momentos,
                   actividades=actividades, obsequios=obsequios)
    arch = {k: await _leer(f) for k, f in subidos.items() if f is not None and f.filename}
    if ventas_fuente:  # ventas desde el histórico guardado (plataforma, Forms o ambas), del mes o universal
        arch["ventas"] = historico.ventas_df(ventas_fuente, ventas_mes or None)
    if not arch:
        raise ErrorArchivo("Sube al menos un archivo.")
    return gerencial.analizar(arch, asesor or None)


# ---------- Histórico de ventas y pronóstico ----------
@app.get("/api/historico")
def api_historico():
    return historico.resumen()


@app.post("/api/historico/plataforma")
async def api_hist_plataforma(archivos: list[UploadFile] = File(...)):
    out = []
    for f in archivos:
        data = await f.read()
        if len(data) > MAX_MB * 1024 * 1024:
            raise ErrorArchivo(f"'{f.filename}' supera {MAX_MB} MB.")
        out.append(historico.cargar_plataforma(leer_hojas(data, f.filename or "archivo"), f.filename or "archivo"))
    return {"cargas": out, **historico.resumen()}


@app.post("/api/historico/forms")
async def api_hist_forms(archivo: UploadFile = File(...)):
    carga = historico.cargar_forms(await _leer(archivo), archivo.filename or "forms")
    return {"carga": carga, **historico.resumen()}


@app.post("/api/historico/borrar")
def api_hist_borrar(fuente: str = Form(...), mes: str | None = Form(None)):
    historico.borrar(fuente, mes or None)
    return historico.resumen()


@app.post("/api/historico/correccion")
def api_hist_correccion(id_resp: int = Form(...), sku: str = Form(...), unidades: str | None = Form(None),
                        precio: str | None = Form(None)):
    historico.corregir(id_resp, sku, unidades or None, precio or None)
    return historico.resumen()


@app.post("/api/pronostico")
def api_pronostico(fuente: str = Form("ambas"), horizonte: int = Form(14)):
    if horizonte not in (7, 14, 28):
        raise ErrorArchivo("El horizonte debe ser 7, 14 o 28 días.")
    return pronostico.analizar(historico.serie_diaria(fuente), horizonte, fuente)
