# Floopbot Startup Script
# 1. Launches TradingView with CDP debugging enabled
# 2. Waits for connection
# 3. Starts the Floopbot dashboard

Write-Host "=== FLOOPBOT STARTUP ===" -ForegroundColor Cyan

# Step 1: Kill existing TradingView
Write-Host "Closing TradingView..." -ForegroundColor Yellow
Get-Process *TradingView* -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 3

# Step 2: Launch TradingView with CDP
Write-Host "Launching TradingView with debug port 9222..." -ForegroundColor Yellow
C:\Windows\System32\cmd.exe /c "start shell:AppsFolder\TradingView.Desktop_n534cwy3pjxzj!TradingView.Desktop --remote-debugging-port=9222"

# Step 3: Wait for CDP to be ready
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
    exit 1
}

Write-Host "CDP connected!" -ForegroundColor Green

# Step 4: Start Floopbot dashboard
Write-Host "Starting Floopbot dashboard at http://localhost:8082" -ForegroundColor Cyan
Set-Location "$env:USERPROFILE\yeaunome"
python -m floopbot --dashboard
