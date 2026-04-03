# Floopbot Startup Script
# 1. Ensures CDP debug wrapper is installed in TradingView
# 2. Launches TradingView with CDP debugging enabled
# 3. Waits for connection
# 4. Starts the Floopbot dashboard

Write-Host "=== FLOOPBOT STARTUP ===" -ForegroundColor Cyan

# Step 1: Ensure the CDP wrapper is in place
$tvResources = "C:\Program Files\WindowsApps\TradingView.Desktop_3.0.0.7652_x64__n534cwy3pjxzj\resources"
$wrapperDir = "$tvResources\app"
$wrapperMain = "$wrapperDir\main.js"

if (-not (Test-Path $wrapperMain)) {
    Write-Host "Installing CDP debug wrapper..." -ForegroundColor Yellow
    New-Item -Path $wrapperDir -ItemType Directory -Force | Out-Null
    Set-Content -Path "$wrapperDir\package.json" -Value '{"name":"tv-debug-wrapper","main":"main.js"}'
    Set-Content -Path $wrapperMain -Value 'const { app } = require("electron"); app.commandLine.appendSwitch("remote-debugging-port", "9222"); require("../app.asar");'
    Write-Host "  Wrapper installed" -ForegroundColor Green
} else {
    Write-Host "CDP wrapper already installed" -ForegroundColor Green
}

# Step 2: Kill existing TradingView
Write-Host "Closing TradingView..." -ForegroundColor Yellow
Get-Process *TradingView* -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 3

# Step 3: Launch TradingView
Write-Host "Launching TradingView with debug port 9222..." -ForegroundColor Yellow
C:\Windows\System32\cmd.exe /c "start shell:AppsFolder\TradingView.Desktop_n534cwy3pjxzj!TradingView.Desktop --remote-debugging-port=9222"

# Step 4: Wait for CDP to be ready
Write-Host "Waiting for CDP connection..." -ForegroundColor Yellow
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep 2
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:9222/json/version" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {}
    Write-Host "  Waiting... ($($i+1))" -ForegroundColor Gray
}

if (-not $ready) {
    Write-Host "ERROR: CDP not available after 60 seconds" -ForegroundColor Red
    Write-Host "Try running as Administrator" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "CDP connected!" -ForegroundColor Green

# Step 5: Start Floopbot dashboard
Write-Host "Starting Floopbot dashboard at http://localhost:8082" -ForegroundColor Cyan
Set-Location "$env:USERPROFILE\yeaunome"
python -m floopbot --dashboard
