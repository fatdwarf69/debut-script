```bat
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
echo ==========================================
echo ETAPE 1 : DETECTION SHOP / DEATH
echo ==========================================
echo.

python "%SCRIPT%" "!SELECTED!"

if errorlevel 1 (
    echo.
    echo ERREUR : La detection a echoue.
    pause
    exit /b 1
)

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

python "%CUT_SCRIPT%" "!SELECTED!"

if errorlevel 1 (
    echo.
    echo ERREUR : Le decoupage a echoue.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo TOUS LES TRAITEMENTS SONT TERMINES !
echo ==========================================
echo.

echo Clips disponibles :
echo %OUTPUT_DIR%\!VIDEO_NAME!\clips

pause
```