
@echo off
setlocal EnableDelayedExpansion

title CS2 Video Analyzer

set "VIDEO_DIR=E:\videos\full"
set "SCRIPT=E:\videos\frames-tri.py"
set "CUT_SCRIPT=E:\videos\cut-frames.py"
set "OUTPUT_DIR=E:\videos\cut"

echo.
echo ==========================================
echo          CS2 VIDEO ANALYZER
echo ==========================================
echo.

if not exist "%VIDEO_DIR%" (
    echo ERREUR : Dossier video introuvable.
    pause
    exit /b 1
)

if not exist "%SCRIPT%" (
    echo ERREUR : Script Python introuvable.
    pause
    exit /b 1
)

if not exist "%CUT_SCRIPT%" (
    echo ERREUR : cut-frames.py introuvable.
    pause
    exit /b 1
)

set /a COUNT=0

echo VIDEOS DISPONIBLES:
echo.

for %%F in ("%VIDEO_DIR%\*.mp4" "%VIDEO_DIR%\*.mkv" "%VIDEO_DIR%\*.mov" "%VIDEO_DIR%\*.avi" "%VIDEO_DIR%\*.webm") do (
    if exist "%%~fF" (
        set /a COUNT+=1
        set "VIDEO_!COUNT!=%%~fF"
        echo [!COUNT!] %%~nxF
    )
)

if !COUNT! EQU 0 (
    echo Aucune video trouvee.
    pause
    exit /b 1
)

echo.
echo ==========================================
set /p "CHOICE=Selectionne une video (numero) : "

set "SELECTED=!VIDEO_%CHOICE%!"

if not defined SELECTED (
    echo Choix invalide.
    pause
    exit /b 1
)

for %%V in ("!SELECTED!") do set "VIDEO_NAME=%%~nV"

set "LOG_FILE=%OUTPUT_DIR%\!VIDEO_NAME!\logs\shop_death_detection.txt"

echo.
echo Video selectionnee : !SELECTED!
echo.

REM CHRONOMETRE TOTAL
for /f %%a in ('powershell -NoProfile -Command "[DateTime]::Now.Ticks"') do set "TOTAL_START=%%a"

echo ==========================================
echo ETAPE 1 : EXTRACTION
echo ==========================================
echo.

REM CHRONOMETRE ETAPE 1
for /f %%a in ('powershell -NoProfile -Command "[DateTime]::Now.Ticks"') do set "START_TIME=%%a"

python "%SCRIPT%" "!SELECTED!"

if errorlevel 1 (
    echo.
    echo ERREUR : La detection a echoue.
    pause
    exit /b 1
)

REM TEMPS ETAPE 1
for /f %%a in ('powershell -NoProfile -Command "[math]::Round(([DateTime]::Now.Ticks - %START_TIME%) / 10000000, 2)"') do set "ELAPSED=%%a"

echo.
echo Detection terminee en !ELAPSED! secondes.
echo.

echo ==========================================
echo VERIFICATION DES LOGS
echo ==========================================
echo.

if not exist "!LOG_FILE!" (
    echo ERREUR : Fichier LOG introuvable.
    echo !LOG_FILE!
    pause
    exit /b 1
)

echo Logs trouves !
echo.

echo ==========================================
echo ETAPE 2 : DECOUPAGE DES CLIPS
echo ==========================================
echo.

REM CHRONOMETRE ETAPE 2
for /f %%a in ('powershell -NoProfile -Command "[DateTime]::Now.Ticks"') do set "START_TIME=%%a"

python "%CUT_SCRIPT%" "!SELECTED!"

if errorlevel 1 (
    echo.
    echo ERREUR : Le decoupage a echoue.
    pause
    exit /b 1
)

REM TEMPS ETAPE 2
for /f %%a in ('powershell -NoProfile -Command "[math]::Round(([DateTime]::Now.Ticks - %START_TIME%) / 10000000, 2)"') do set "ELAPSED=%%a"

echo.
echo Decoupage termine en !ELAPSED! secondes.
echo.

REM TEMPS TOTAL
for /f %%a in ('powershell -NoProfile -Command "[math]::Round(([DateTime]::Now.Ticks - %TOTAL_START%) / 10000000, 2)"') do set "TOTAL_ELAPSED=%%a"

echo.
echo ==========================================
echo TOUS LES TRAITEMENTS SONT TERMINES !
echo ==========================================
echo.

echo Temps total : !TOTAL_ELAPSED! secondes.
echo.

echo Clips disponibles :
echo %OUTPUT_DIR%\!VIDEO_NAME!\clips

pause

```