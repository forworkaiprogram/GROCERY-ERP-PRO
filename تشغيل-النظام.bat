@echo off
chcp 65001 >nul
title GROCERY ERP PRO
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [خطأ] Python غير مثبت. ثبّته من python.org ثم أعد تشغيل هذا الملف.
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo إنشاء بيئة التشغيل لأول مرة...
    python -m venv venv
    if errorlevel 1 (
        echo [خطأ] فشل إنشاء البيئة.
        pause
        exit /b 1
    )
    echo تثبيت المكتبات المطلوبة (مرة واحدة فقط، يحتاج إنترنت)...
    venv\Scripts\python -m pip install --upgrade pip
    venv\Scripts\pip install -r requirements-desktop.txt
    if errorlevel 1 (
        echo [خطأ] فشل تثبيت المكتبات - تأكد من الاتصال بالإنترنت ثم أعد المحاولة.
        pause
        exit /b 1
    )
)

echo تشغيل GROCERY ERP PRO ...
venv\Scripts\python run_desktop.py
if errorlevel 1 (
    echo.
    echo انتهى التشغيل برمز خطأ. عادةً رمز 3 يعني تعذر بدء Qt.
    pause
)
