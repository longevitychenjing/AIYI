@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
set "PREVIEW_URL=http://127.0.0.1:4173/three-step.html"
set "OLLAMA_URL=http://127.0.0.1:11434"
set "OLLAMA_MODEL=qwen2.5:7b"
set "API_URL=http://127.0.0.1:8000"
set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
set "PYTHON_EXE=%ROOT%.venv\Scripts\python.exe"

if not exist "%OLLAMA_EXE%" (
  for /f "delims=" %%I in ('where ollama.exe 2^>nul') do if not defined OLLAMA_FOUND set "OLLAMA_FOUND=%%~fI"
  if defined OLLAMA_FOUND set "OLLAMA_EXE=!OLLAMA_FOUND!"
)
if not exist "%OLLAMA_EXE%" (
  echo Ollama was not found. Install Ollama first.
  pause
  exit /b 1
)

if not exist "%PYTHON_EXE%" (
  for /f "delims=" %%I in ('where python.exe 2^>nul') do if not defined PYTHON_FOUND set "PYTHON_FOUND=%%~fI"
  if defined PYTHON_FOUND set "PYTHON_EXE=!PYTHON_FOUND!"
)
if not exist "%PYTHON_EXE%" (
  echo Python was not found. Install Python 3.11 or create .venv first.
  pause
  exit /b 1
)

set "PYTHONPATH=%ROOT%apps\api\src;%ROOT%packages\liuyao\src"
set "OLLAMA_HOST=127.0.0.1:11434"

echo [1/5] Starting Ollama service...
call :port_ready 11434
if errorlevel 1 start "Yijing Ollama" /min "%OLLAMA_EXE%" serve
call :wait_for_port 11434 60 "Ollama"
if errorlevel 1 exit /b 1

echo [2/5] Checking %OLLAMA_MODEL%...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$models=(Invoke-RestMethod -UseBasicParsing -TimeoutSec 5 -Uri '%OLLAMA_URL%/api/tags').models.name; if ($models -contains '%OLLAMA_MODEL%') { exit 0 } else { exit 1 }"
if errorlevel 1 (
  echo Model is missing. Pulling %OLLAMA_MODEL%...
  start "" /wait "%OLLAMA_EXE%" pull "%OLLAMA_MODEL%"
  if errorlevel 1 (
    echo Failed to pull %OLLAMA_MODEL%.
    pause
    exit /b 1
  )
)

echo [3/5] Warming %OLLAMA_MODEL%...
"%OLLAMA_EXE%" run "%OLLAMA_MODEL%" "Reply with READY only." >nul 2>&1
if errorlevel 1 echo Warning: Ollama warm-up failed; the API will retry on the first reading.

echo [4/5] Starting API...
call :port_ready 8000
if errorlevel 1 start "Yijing API" /min /D "%ROOT%" "%PYTHON_EXE%" -B -m uvicorn yijing_ai.main:app --app-dir "%ROOT%apps\api\src" --env-file "%ROOT%.env" --host 127.0.0.1 --port 8000
call :wait_for_port 8000 45 "API"
if errorlevel 1 exit /b 1

echo [5/5] Starting three-step preview...
call :port_ready 4173
if errorlevel 1 start "Yijing three-step preview" /min /D "%ROOT%" "%PYTHON_EXE%" -B -m http.server 4173 --directory "%ROOT%preview"
call :wait_for_port 4173 15 "Preview"
if errorlevel 1 exit /b 1

start "" "%PREVIEW_URL%"
echo Ready: %PREVIEW_URL%
endlocal
exit /b 0

:port_ready
netstat -ano | findstr /R /C:":%~1 .*LISTENING" >nul 2>&1
exit /b %ERRORLEVEL%

:wait_for_port
set "WAIT_PORT=%~1"
set "WAIT_LIMIT=%~2"
set "WAIT_NAME=%~3"
for /l %%N in (1,1,!WAIT_LIMIT!) do (
  call :port_ready !WAIT_PORT!
  if not errorlevel 1 exit /b 0
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 1"
)
echo !WAIT_NAME! did not become ready on port !WAIT_PORT!.
pause
exit /b 1
