@echo off
cd /d "%~dp0"
if not exist .venv (
  echo Creando entorno e instalando dependencias (solo la primera vez)...
  python -m venv .venv || goto :error
  .venv\Scripts\python -m pip install -q -r requirements.txt || goto :error
)
start "" http://localhost:8000
.venv\Scripts\python -m uvicorn app:app --app-dir backend --port 8000
goto :eof
:error
echo No se pudo preparar el entorno. Verifica que Python 3.10+ este instalado.
pause
