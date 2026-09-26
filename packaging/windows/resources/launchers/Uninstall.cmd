@echo off
echo Removing the NMR Companion runtime. Your projects and outputs will be retained.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Manage-Installation.ps1" -Action Uninstall -Root "%~dp0."
pause
