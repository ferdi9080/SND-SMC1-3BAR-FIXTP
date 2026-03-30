@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ===================== WAJIB DIISI =====================
set TELEGRAM_BOT_TOKEN=8234770186:AAFpfeohygIDg7Fw_LJLLZ3jZKnJZL-I_XU
set TELEGRAM_CHAT_ID=-1002163563793

REM (SANGAT DISARANKAN) Pisahkan chat:
REM - SIGNALS: hanya pesan entry (dibaca Cornix)
REM - UPDATES: update + gambar chart (Cornix aman)
set TELEGRAM_CHAT_ID_SIGNALS=
set TELEGRAM_CHAT_ID_UPDATES=

set TV_USERNAME=
set TV_PASSWORD=

REM ===================== CORNIX =====================
set CORNIX_ENABLED=1
set CORNIX_EXCHANGE=Binance Futures
set CORNIX_LEVERAGE=Cross (20X)

REM ===================== TP/SL ROI =====================
set TP_SL_MODE=ROI
set LEVERAGE=20
set TP_ROI_1=75
set TP_ROI_2=120
set TP_ROI_3=200
set SL_ROI=100

REM ===================== UPDATE AMAN =====================
set CORNIX_SAFE_UPDATES=1

REM ===================== CHART IMAGE (ZONA SAJA) =====================
set SEND_CHART_IMAGE=1
set CHART_IMAGE_CHAT=UPDATES
set CHART_BARS=120
set CHART_DPI=140
set CHART_SHOW_LABELS=0

REM ===================== RETRY TRADINGVIEW =====================
set TV_RETRY=5
set TV_RETRY_WAIT=2

REM ===================== LAINNYA =====================
set SYMBOLS=ALL
set MAX_SYMBOLS=80
set LOOP_SLEEP_SEC=10

python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt

python tradingview_signal_bot.py
pause
