@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Manage-Installation.ps1" -Action Install -Bundle "%~dp0." %*
if errorlevel 1 (
  echo Installation did not complete. Existing projects and installations were preserved.
) else (
  echo Open NMR Companion.cmd in the reported installation folder to start the workbench.
)
pause
