@echo off
rem This script lives in scripts\tools\; every path below is repo-root-relative.
cd /d "%~dp0..\.."

if not exist "bin\tailwindcss.exe" (
    echo BLAD: bin\tailwindcss.exe nie znaleziony. Uruchom install.bat.
    pause
    exit /b 1
)

echo Budowanie stylow (static\css\input.css + brand.css -^> output.css)...
bin\tailwindcss.exe -i static\css\input.css -o static\css\output.css --minify
if errorlevel 1 (
    echo BLAD: Budowanie stylow nie powiodlo sie.
    pause
    exit /b 1
)
echo Gotowe.
