param(
  [string]$ServiceName = "CondoChargeAgent"
)

$ErrorActionPreference = "Stop"

sc.exe stop $ServiceName | Out-Null
Start-Sleep -Seconds 1
sc.exe start $ServiceName | Out-Null

$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
  $s = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
  if ($null -ne $s -and $s.Status -eq "Running") { break }
  Start-Sleep -Milliseconds 500
}

$final = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($null -eq $final) { throw "Service not found: $ServiceName" }
if ($final.Status -ne "Running") { throw "Service failed to reach Running. Current status: $($final.Status)" }

Write-Host "Service running: $ServiceName"
