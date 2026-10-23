@echo off
title TradingAgents - Stop Servers
echo ================================================================
echo           Stopping TradingAgents Servers (Ports 8000 and 3000)
echo ================================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports = 8000, 3000; $killed = 0; foreach ($p in $ports) { $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue; if ($conns) { foreach ($c in $conns) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Host ('[STOPPED] Process on port ' + $p + ' (PID: ' + $c.OwningProcess + ')'); $killed++ } } }; if ($killed -eq 0) { Write-Host '[INFO] No running servers found on port 8000 or 3000.' } else { Write-Host ('[DONE] Successfully stopped ' + $killed + ' server process(es).') }"

echo.
echo ================================================================
pause
