@echo off
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py smart_mouse_clicker.py
  goto :done
)

where python >nul 2>nul
if not errorlevel 1 (
  python smart_mouse_clicker.py
  goto :done
)

set "CODEX_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%CODEX_PYTHON%" (
  "%CODEX_PYTHON%" smart_mouse_clicker.py
  goto :done
)

echo.
echo Python could not run the clicker. Install Python from https://www.python.org/downloads/
pause

:done
