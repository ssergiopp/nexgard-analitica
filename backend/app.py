"""API de la plataforma analítica NexGard. Procesa los archivos en memoria y los descarta.

Ejecutar desde la carpeta del proyecto:  python -m uvicorn app:app --app-dir backend --port 8000
"""
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import comisiones
import encuestas
import gerencial
from lectura import ErrorArchivo, leer

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


@app.get("/")
def inicio():
    return FileResponse(FRONT)


@app.get("/api/salud")
def salud():
    return {"ok": True}


@app.post("/api/encuestas")
async def api_encuestas(
    cadenas: UploadFile = File(...), rutero: UploadFile = File(...), encuesta: UploadFile = File(...),
    periodo: str = Form("Mensual"), mes: str | None = Form(None),
):
    if periodo not in ("Mensual", "Universal"):
        raise ErrorArchivo("El periodo debe ser Mensual o Universal.")
    return encuestas.analizar(await _leer(cadenas), await _leer(rutero, "PDVS"), await _leer(encuesta), periodo, mes)


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
):
    subidos = dict(ventas=ventas, agotados=agotados, cobertura=cobertura, momentos=momentos,
                   actividades=actividades, obsequios=obsequios)
    arch = {k: await _leer(f) for k, f in subidos.items() if f is not None and f.filename}
    if not arch:
        raise ErrorArchivo("Sube al menos un archivo.")
    return gerencial.analizar(arch)
