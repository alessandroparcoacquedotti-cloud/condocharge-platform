param(
    [string]$ProjectName = "natural-curiosity",
    [string]$ServiceName = "condocharge-prod",
    [string]$VolumeName = "condocharge-prod-volume",
    [string]$RemoteDatabasePath = "/data/pilot_real.sqlite3",
    [string]$BackupRoot = (Join-Path $PSScriptRoot "backups\railway-prod"),
    [string]$RailwayCommand = "railway",
    [string]$PythonCommand = "python",
    [datetime]$TimestampUtc = (Get-Date).ToUniversalTime(),
    [switch]$ForceWeekly,
    [switch]$ForceMonthly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-CommandAvailable {
    param([string]$CommandName)
    if (-not (Get-Command -Name $CommandName -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $CommandName"
    }
}

function Invoke-ExternalCommand {
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    $output = & $Executable @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if (-not $AllowFailure -and $exitCode -ne 0) {
        $message = ($output | ForEach-Object { "$_" }) -join [Environment]::NewLine
        throw "Command failed: $Executable $($Arguments -join ' ')`n$message"
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output   = @($output | ForEach-Object { "$_" })
    }
}

function Invoke-PythonHelper {
    param([string[]]$Arguments)
    $pythonArgs = @("-m", "condocharge.tools.sqlite_backup") + $Arguments
    return Invoke-ExternalCommand -Executable $PythonCommand -Arguments $pythonArgs
}

function Prune-BackupDirectory {
    param(
        [string]$DirectoryPath,
        [int]$KeepCount
    )

    if (-not (Test-Path -LiteralPath $DirectoryPath)) {
        return
    }

    $archives = @(Get-ChildItem -LiteralPath $DirectoryPath -Filter "*.zip" | Sort-Object -Property LastWriteTimeUtc, Name -Descending)
    if ($archives.Count -le $KeepCount) {
        return
    }

    foreach ($archive in $archives[$KeepCount..($archives.Count - 1)]) {
        $manifestPath = Join-Path $DirectoryPath ("{0}.manifest.json" -f [IO.Path]::GetFileNameWithoutExtension($archive.Name))
        Remove-Item -LiteralPath $archive.FullName -Force
        if (Test-Path -LiteralPath $manifestPath) {
            Remove-Item -LiteralPath $manifestPath -Force
        }
    }
}

Assert-CommandAvailable -CommandName $RailwayCommand
Assert-CommandAvailable -CommandName $PythonCommand

$timestamp = $TimestampUtc.ToUniversalTime()
$timestampText = $timestamp.ToString("yyyyMMddTHHmmssZ")
$baseName = "pilot_real_$timestampText"
$backupDirectories = @{
    daily   = Join-Path $BackupRoot "daily"
    weekly  = Join-Path $BackupRoot "weekly"
    monthly = Join-Path $BackupRoot "monthly"
}

foreach ($directory in $backupDirectories.Values) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("condocharge-backup-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

try {
    $downloadRoot = Join-Path $tempRoot "download"
    New-Item -ItemType Directory -Force -Path $downloadRoot | Out-Null

    $downloadedDbPath = Join-Path $downloadRoot "pilot_real.sqlite3"
    $downloadedWalPath = "$downloadedDbPath-wal"
    $downloadedShmPath = "$downloadedDbPath-shm"

    Invoke-ExternalCommand -Executable $RailwayCommand -Arguments @(
        "volume", "files", "download",
        "--volume", $VolumeName,
        $RemoteDatabasePath,
        $downloadedDbPath,
        "--overwrite",
        "--json"
    ) | Out-Null

    Invoke-ExternalCommand -Executable $RailwayCommand -Arguments @(
        "volume", "files", "download",
        "--volume", $VolumeName,
        "$RemoteDatabasePath-wal",
        $downloadedWalPath,
        "--overwrite",
        "--json"
    ) -AllowFailure | Out-Null

    Invoke-ExternalCommand -Executable $RailwayCommand -Arguments @(
        "volume", "files", "download",
        "--volume", $VolumeName,
        "$RemoteDatabasePath-shm",
        $downloadedShmPath,
        "--overwrite",
        "--json"
    ) -AllowFailure | Out-Null

    $snapshotPath = Join-Path $tempRoot "backup_snapshot.sqlite3"
    Invoke-PythonHelper -Arguments @(
        "snapshot",
        "--source-db-path", $downloadedDbPath,
        "--snapshot-db-path", $snapshotPath
    ) | Out-Null

    $manifestPath = Join-Path $tempRoot "backup_manifest.json"
    Invoke-PythonHelper -Arguments @(
        "inspect",
        "--db-path", $snapshotPath,
        "--output-json", $manifestPath,
        "--remote-db-path", $RemoteDatabasePath,
        "--volume-name", $VolumeName,
        "--service-name", $ServiceName,
        "--project-name", $ProjectName,
        "--captured-at", $timestamp.ToString("o"),
        "--require-ok"
    ) | Out-Null

    $dailyArchivePath = Join-Path $backupDirectories.daily "$baseName.zip"
    $dailyManifestPath = Join-Path $backupDirectories.daily "$baseName.manifest.json"
    Compress-Archive -LiteralPath @($snapshotPath, $manifestPath) -DestinationPath $dailyArchivePath -CompressionLevel Optimal -Force
    Copy-Item -LiteralPath $manifestPath -Destination $dailyManifestPath -Force

    $createdTiers = @("daily")
    $isWeekly = $ForceWeekly.IsPresent -or $timestamp.DayOfWeek -eq [System.DayOfWeek]::Sunday
    if ($isWeekly) {
        $weeklyArchivePath = Join-Path $backupDirectories.weekly "$baseName.zip"
        $weeklyManifestPath = Join-Path $backupDirectories.weekly "$baseName.manifest.json"
        Copy-Item -LiteralPath $dailyArchivePath -Destination $weeklyArchivePath -Force
        Copy-Item -LiteralPath $dailyManifestPath -Destination $weeklyManifestPath -Force
        $createdTiers += "weekly"
    }

    $isMonthly = $ForceMonthly.IsPresent -or $timestamp.Day -eq 1
    if ($isMonthly) {
        $monthlyArchivePath = Join-Path $backupDirectories.monthly "$baseName.zip"
        $monthlyManifestPath = Join-Path $backupDirectories.monthly "$baseName.manifest.json"
        Copy-Item -LiteralPath $dailyArchivePath -Destination $monthlyArchivePath -Force
        Copy-Item -LiteralPath $dailyManifestPath -Destination $monthlyManifestPath -Force
        $createdTiers += "monthly"
    }

    Prune-BackupDirectory -DirectoryPath $backupDirectories.daily -KeepCount 7
    Prune-BackupDirectory -DirectoryPath $backupDirectories.weekly -KeepCount 4
    Prune-BackupDirectory -DirectoryPath $backupDirectories.monthly -KeepCount 6

    $manifest = Get-Content -LiteralPath $dailyManifestPath -Raw | ConvertFrom-Json
    [pscustomobject]@{
        backup_root      = $BackupRoot
        archive_path     = $dailyArchivePath
        manifest_path    = $dailyManifestPath
        created_tiers    = $createdTiers
        retention_policy = @{
            daily   = 7
            weekly  = 4
            monthly = 6
        }
        inspection       = $manifest.inspection
    } | ConvertTo-Json -Depth 8
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
