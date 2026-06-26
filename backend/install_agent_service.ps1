param(
  [string]$ServiceName = "CondoChargeAgent",
  [string]$ServiceDisplayName = "CondoCharge Agent",
  [string]$PythonExe = "python",
  [string]$PythonClass = "condocharge.tools.agent_service.CondoChargeAgentService",
  [string]$EnvFile = "$env:ProgramData\\CondoCharge\\Agent\\.env",
  [string]$LogDir = "$env:ProgramData\\CondoCharge\\Agent\\logs",
  [switch]$SkipOnlineValidation
)

$ErrorActionPreference = "Stop"

function Assert-FileExists([string]$PathValue, [string]$Label) {
  if (-not (Test-Path -LiteralPath $PathValue)) {
    throw "$Label not found: $PathValue"
  }
}

function Resolve-PythonExe([string]$Value) {
  if (Test-Path -LiteralPath $Value) { return (Resolve-Path -LiteralPath $Value).Path }
  $cmd = Get-Command $Value -ErrorAction SilentlyContinue
  if ($null -eq $cmd) { throw "Python executable not found: $Value" }
  return $cmd.Path
}

function Assert-PythonInterpreter([string]$PythonExeResolved) {
  Assert-FileExists $PythonExeResolved "Python executable"
  $ver = & $PythonExeResolved -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
  if ($LASTEXITCODE -ne 0) { throw "Python interpreter failed to run: $PythonExeResolved" }
  $parts = $ver.Trim().Split(".")
  if ($parts.Length -lt 2) { throw "Unexpected Python version output: $ver" }
  $major = [int]$parts[0]
  $minor = [int]$parts[1]
  if ($major -ne 3 -or $minor -lt 12) { throw "Python 3.12+ required. Found: $ver" }
}

function Get-PythonServiceExe([string]$PythonExeResolved) {
  $pythonDir = Split-Path -Parent $PythonExeResolved
  return (Join-Path $pythonDir "pythonservice.exe")
}

function Assert-PythonServiceHost([string]$PythonServiceExe) {
  Assert-FileExists $PythonServiceExe "pythonservice.exe"
}

function Read-EnvKeys([string]$PathValue) {
  $keys = New-Object System.Collections.Generic.HashSet[string]
  $lines = Get-Content -LiteralPath $PathValue -ErrorAction Stop
  foreach ($line in $lines) {
    $t = $line.Trim()
    if ($t.Length -eq 0) { continue }
    if ($t.StartsWith("#")) { continue }
    if ($t.StartsWith("export ")) { $t = $t.Substring(7).Trim() }
    $idx = $t.IndexOf("=")
    if ($idx -lt 1) { continue }
    $key = $t.Substring(0, $idx).Trim()
    if ($key.Length -gt 0) { [void]$keys.Add($key) }
  }
  return $keys
}

function Assert-EnvFile([string]$PathValue) {
  Assert-FileExists $PathValue ".env file"
  $keys = Read-EnvKeys $PathValue
  $required = @(
    "CONDOCHARGE_AGENT_API_BASE_URL",
    "CONDOCHARGE_AGENT_TOKEN",
    "CONDOCHARGE_AGENT_ID",
    "CONDOCHARGE_AGENT_CONDOMINIUM_ID",
    "CONDOCHARGE_AGENT_HOSTS",
    "CONDOCHARGE_LEGRAND_USERNAME",
    "CONDOCHARGE_LEGRAND_PASSWORD"
  )
  foreach ($k in $required) {
    if (-not $keys.Contains($k)) { throw ".env missing required key: $k" }
  }
}

function Assert-PythonClassImportable([string]$PythonExeResolved, [string]$BackendSrc, [string]$PythonClassValue) {
  $script = @"
import importlib, sys
sys.path.insert(0, r'$BackendSrc')
value = r'$PythonClassValue'
mod, cls = value.rsplit('.', 1)
m = importlib.import_module(mod)
getattr(m, cls)
"@
  & $PythonExeResolved -c $script
  if ($LASTEXITCODE -ne 0) { throw "PythonClass import failed: $PythonClassValue" }
}

function Assert-ServiceWrapperInit([string]$PythonExeResolved, [string]$BackendSrc, [string]$PythonClassValue) {
  $script = @"
import importlib, sys
sys.path.insert(0, r'$BackendSrc')
value = r'$PythonClassValue'
mod, cls = value.rsplit('.', 1)
m = importlib.import_module(mod)
klass = getattr(m, cls)
klass([])
"@
  & $PythonExeResolved -c $script
  if ($LASTEXITCODE -ne 0) { throw "Service wrapper initialization failed for: $PythonClassValue" }
}

function Assert-AgentHeartbeat([string]$PythonExeResolved, [string]$BackendSrc, [string]$EnvFilePath) {
  $env:CONDOCHARGE_AGENT_ENV_FILE = $EnvFilePath
  $env:PYTHONPATH = $BackendSrc
  & $PythonExeResolved -m condocharge.tools.agent heartbeat-once
  if ($LASTEXITCODE -ne 0) { throw "Agent heartbeat validation failed (check token/network/backend): $EnvFilePath" }
}

$pythonResolved = Resolve-PythonExe $PythonExe
Assert-PythonInterpreter $pythonResolved

$backendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendSrc = Join-Path $backendRoot "src"
Assert-FileExists $backendSrc "Backend src folder"

$pythonServiceExe = Get-PythonServiceExe $pythonResolved
Assert-PythonServiceHost $pythonServiceExe

Assert-EnvFile $EnvFile
Assert-PythonClassImportable $pythonResolved $backendSrc $PythonClass
Assert-ServiceWrapperInit $pythonResolved $backendSrc $PythonClass

if (-not $SkipOnlineValidation) {
  Assert-AgentHeartbeat $pythonResolved $backendSrc $EnvFile
}

$svcExists = (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)
if ($null -ne $svcExists) {
  try { sc.exe stop $ServiceName | Out-Null } catch { }
  Start-Sleep -Seconds 1
  try { sc.exe delete $ServiceName | Out-Null } catch { }
  Start-Sleep -Seconds 1
}

sc.exe create $ServiceName binPath= "`"$pythonServiceExe`"" start= auto DisplayName= "`"$ServiceDisplayName`"" | Out-Null
sc.exe description $ServiceName "Autonomous CondoCharge agent service for heartbeat, polling, and session import." | Out-Null

$paramsKey = "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\$ServiceName\\Parameters"
New-Item -Path $paramsKey -Force | Out-Null
New-ItemProperty -Path $paramsKey -Name "PythonClass" -PropertyType String -Value $PythonClass -Force | Out-Null

$envMulti = @(
  "CONDOCHARGE_AGENT_ENV_FILE=$EnvFile",
  "CONDOCHARGE_AGENT_LOG_DIR=$LogDir",
  "PYTHONPATH=$backendSrc",
  "PYTHONUTF8=1"
)
New-ItemProperty -Path "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\$ServiceName" -Name "Environment" -PropertyType MultiString -Value $envMulti -Force | Out-Null

sc.exe failure $ServiceName reset= 86400 actions= restart/0/restart/0/restart/60000 | Out-Null
sc.exe failureflag $ServiceName 1 | Out-Null

sc.exe start $ServiceName | Out-Null

$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
  $s = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
  if ($null -ne $s -and $s.Status -eq "Running") { break }
  Start-Sleep -Milliseconds 500
}

$final = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($null -eq $final) { throw "Service not found after install: $ServiceName" }
if ($final.Status -ne "Running") { throw "Service failed to reach Running. Current status: $($final.Status)" }

Write-Host "Service installed and running: $ServiceName"
