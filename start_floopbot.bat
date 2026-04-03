@echo off
echo === FLOOPBOT STARTUP ===
taskkill /F /IM TradingView.exe 2>nul
timeout /t 3 /nobreak >nul
echo Launching TradingView...
start shell:AppsFolder\TradingView.Desktop_n534cwy3pjxzj!TradingView.Desktop --remote-debugging-port=9222
echo Waiting for TradingView to start...
timeout /t 10 /nobreak >nul
cd /d "%USERPROFILE%\yeaunome"
echo Starting Floopbot dashboard at http://localhost:8082
python -m floopbot --dashboard
pause
