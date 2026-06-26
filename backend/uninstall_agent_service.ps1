param(
  [string]$ServiceName = "CondoChargeAgent"
)

$ErrorActionPreference = "Stop"

try { sc.exe stop $ServiceName | Out-Null } catch { }
Start-Sleep -Seconds 1
try { sc.exe delete $ServiceName | Out-Null } catch { }

Write-Host "Service removed (if it existed): $ServiceName"
