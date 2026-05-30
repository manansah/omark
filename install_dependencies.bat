@echo off
setlocal

cd /d "%~dp0"

where winget >nul 2>&1
if errorlevel 1 (
    echo winget was not found. Install Tesseract OCR manually from:
    echo https://github.com/UB-Mannheim/tesseract/wiki
) else (
    echo Installing Tesseract OCR...
    winget install --id UB-Mannheim.TesseractOCR --exact --accept-package-agreements --accept-source-agreements
    echo Installing FFmpeg for MarkItDown audio support...
    winget install --id Gyan.FFmpeg --exact --accept-package-agreements --accept-source-agreements
)

if not exist ".tessdata" mkdir ".tessdata"
if not exist ".tessdata\eng.traineddata" (
    echo Installing English OCR language data...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata' -OutFile '.tessdata\eng.traineddata'"
)
if not exist ".tessdata\hin.traineddata" (
    echo Installing Hindi OCR language data...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://github.com/tesseract-ocr/tessdata_fast/raw/main/hin.traineddata' -OutFile '.tessdata\hin.traineddata'"
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    py -3 -m venv .venv
)

echo Installing Python packages for PDF, Word, Excel, and PowerPoint conversion...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo.
echo Setup complete. Run run_omark.bat to start OMark.
pause
