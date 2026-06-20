param(
    [Parameter(Mandatory = $true)]
    [string]$BackupArchivePath,
    [string]$ProjectName = "natural-curiosity",
    [string]$ServiceName = "condocharge-prod",
    [string]$VolumeName = "condocharge-prod-volume",
    [string]$RemoteDatabasePath = "/data/pilot_real.sqlite3",
    [string]$BackupRoot = (Join-Path $PSScriptRoot "backups\railway-prod"),
    [string]$RailwayCommand = "railway",
    [string]$PythonCommand = "python",
    [datetime]$TimestampUtc = (Get-Date).ToUniversalTime()
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

function Get-JsonFromFile {
    param([string]$Path)
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Download-RemoteDatabaseSet {
    param(
        [string]$TargetDirectory,
        [string]$RemotePath,
        [string]$LocalFileName
    )

    New-Item -ItemType Directory -Force -Path $TargetDirectory | Out-Null
    $localDbPath = Join-Path $TargetDirectory $LocalFileName

    Invoke-ExternalCommand -Executable $RailwayCommand -Arguments @(
        "volume", "files", "download",
        "--volume", $VolumeName,
        $RemotePath,
        $localDbPath,
        "--overwrite",
        "--json"
    ) | Out-Null

    Invoke-ExternalCommand -Executable $RailwayCommand -Arguments @(
        "volume", "files", "download",
        "--volume", $VolumeName,
        "$RemotePath-wal",
        "$localDbPath-wal",
        "--overwrite",
        "--json"
    ) -AllowFailure | Out-Null

    Invoke-ExternalCommand -Executable $RailwayCommand -Arguments @(
        "volume", "files", "download",
        "--volume", $VolumeName,
        "$RemotePath-shm",
        "$localDbPath-shm",
        "--overwrite",
        "--json"
    ) -AllowFailure | Out-Null

    return $localDbPath
}

function Compare-InspectionResults {
    param(
        $ExpectedInspection,
        $ActualInspection
    )

    foreach ($tableName in @("charging_sessions", "charging_stations", "agent_states", "app_users")) {
        $expectedValue = $ExpectedInspection.row_counts.$tableName
        $actualValue = $ActualInspection.row_counts.$tableName
        if ($expectedValue -ne $actualValue) {
            throw "Row count mismatch for $tableName. Expected '$expectedValue' but found '$actualValue'."
        }
    }

    if ($ExpectedInspection.alembic_version -ne $ActualInspection.alembic_version) {
        throw "Alembic version mismatch. Expected '$($ExpectedInspection.alembic_version)' but found '$($ActualInspection.alembic_version)'."
    }

    if ($ActualInspection.integrity_check -ne "ok") {
        throw "Post-restore integrity check failed: $($ActualInspection.integrity_check)"
    }
}

Assert-CommandAvailable -CommandName $RailwayCommand
Assert-CommandAvailable -CommandName $PythonCommand

$backupArchiveResolved = (Resolve-Path -LiteralPath $BackupArchivePath).Path
$timestamp = $TimestampUtc.ToUniversalTime()
$timestampText = $timestamp.ToString("yyyyMMddTHHmmssZ")
$preRestoreDirectory = Join-Path $BackupRoot "pre-restore"
New-Item -ItemType Directory -Force -Path $preRestoreDirectory | Out-Null

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("condocharge-restore-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

try {
    $extractedBackupRoot = Join-Path $tempRoot "selected-backup"
    Expand-Archive -LiteralPath $backupArchiveResolved -DestinationPath $extractedBackupRoot -Force
    $restoredSnapshotPath = Join-Path $extractedBackupRoot "backup_snapshot.sqlite3"
    $restoredManifestPath = Join-Path $extractedBackupRoot "backup_manifest.json"
    if (-not (Test-Path -LiteralPath $restoredSnapshotPath)) {
        throw "Backup archive does not contain backup_snapshot.sqlite3"
    }
    if (-not (Test-Path -LiteralPath $restoredManifestPath)) {
        throw "Backup archive does not contain backup_manifest.json"
    }

    $selectedManifestPath = Join-Path $tempRoot "selected-backup.manifest.json"
    Invoke-PythonHelper -Arguments @(
        "inspect",
        "--db-path", $restoredSnapshotPath,
        "--output-json", $selectedManifestPath,
        "--remote-db-path", $RemoteDatabasePath,
        "--volume-name", $VolumeName,
        "--service-name", $ServiceName,
        "--project-name", $ProjectName,
        "--captured-at", $timestamp.ToString("o"),
        "--require-ok"
    ) | Out-Null
    $selectedManifest = Get-JsonFromFile -Path $selectedManifestPath

    $currentDownloadRoot = Join-Path $tempRoot "current-db"
    $currentDownloadedDb = Download-RemoteDatabaseSet -TargetDirectory $currentDownloadRoot -RemotePath $RemoteDatabasePath -LocalFileName "current.sqlite3"
    $currentSnapshotPath = Join-Path $tempRoot "current_snapshot.sqlite3"
    Invoke-PythonHelper -Arguments @(
        "snapshot",
        "--source-db-path", $currentDownloadedDb,
        "--snapshot-db-path", $currentSnapshotPath
    ) | Out-Null

    $preRestoreManifestPath = Join-Path $tempRoot "pre_restore_manifest.json"
    Invoke-PythonHelper -Arguments @(
        "inspect",
        "--db-path", $currentSnapshotPath,
        "--output-json", $preRestoreManifestPath,
        "--remote-db-path", $RemoteDatabasePath,
        "--volume-name", $VolumeName,
        "--service-name", $ServiceName,
        "--project-name", $ProjectName,
        "--captured-at", $timestamp.ToString("o"),
        "--require-ok"
    ) | Out-Null

    $preRestoreArchiveBase = "pilot_real_pre_restore_$timestampText"
    $preRestoreArchivePath = Join-Path $preRestoreDirectory "$preRestoreArchiveBase.zip"
    $preRestoreManifestCopy = Join-Path $preRestoreDirectory "$preRestoreArchiveBase.manifest.json"
    Compress-Archive -LiteralPath @($currentSnapshotPath, $preRestoreManifestPath) -DestinationPath $preRestoreArchivePath -CompressionLevel Optimal -Force
    Copy-Item -LiteralPath $preRestoreManifestPath -Destination $preRestoreManifestCopy -Force

    $remoteStagePath = "$RemoteDatabasePath.restore_$timestampText"
    $remoteRollbackPath = "$RemoteDatabasePath.pre_restore_$timestampText"
    $remoteRollbackWalPath = "$remoteRollbackPath-wal"
    $remoteRollbackShmPath = "$remoteRollbackPath-shm"
    $rollbackCreated = $false
    $stageMoved = $false

    try {
        Invoke-ExternalCommand -Executable $RailwayCommand -Arguments @(
            "volume", "files", "upload",
            "--volume", $VolumeName,
            $restoredSnapshotPath,
            $remoteStagePath,
            "--overwrite",
            "--json"
        ) | Out-Null

        Invoke-ExternalCommand -Executable $RailwayCommand -Arguments @(
            "volume", "files", "rename",
            "--volume", $VolumeName,
            $RemoteDatabasePath,
            $remoteRollbackPath,
            "--json"
        ) | Out-Null
        $rollbackCreated = $true

        Invoke-ExternalCommand -Executable $RailwayCommand -Arguments @(
            "volume", "files", "rename",
            "--volume", $VolumeName,
            "$RemoteDatabasePath-wal",
            $remoteRollbackWalPath,
            "--json"
        ) -AllowFailure | Out-Null

        Invoke-ExternalCommand -Executable $RailwayCommand -Arguments @(
            "volume", "files", "rename",
            "--volume", $VolumeName,
            "$RemoteDatabasePath-shm",
            $remoteRollbackShmPath,
            "--json"
        ) -AllowFailure | Out-Null

        Invoke-ExternalCommand -Executable $RailwayCommand -Arguments @(
            "volume", "files", "rename",
            "--volume", $VolumeName,
            $remoteStagePath,
            $RemoteDatabasePath,
            "--json"
        ) | Out-Null
        $stageMoved = $true
    }
    catch {
        if ($rollbackCreated -and -not $stageMoved) {
            Invoke-ExternalCommand -Executable $RailwayCommand -Arguments @(
                "volume", "files", "rename",
                "--volume", $VolumeName,
                $remoteRollbackPath,
                $RemoteDatabasePath,
                "--json"
            ) -AllowFailure | Out-Null

            Invoke-ExternalCommand -Executable $RailwayCommand -Arguments @(
                "volume", "files", "rename",
                "--volume", $VolumeName,
                $remoteRollbackWalPath,
                "$RemoteDatabasePath-wal",
                "--json"
            ) -AllowFailure | Out-Null

            Invoke-ExternalCommand -Executable $RailwayCommand -Arguments @(
                "volume", "files", "rename",
                "--volume", $VolumeName,
                $remoteRollbackShmPath,
                "$RemoteDatabasePath-shm",
                "--json"
            ) -AllowFailure | Out-Null
        }

        throw
    }

    Invoke-ExternalCommand -Executable $RailwayCommand -Arguments @(
        "service", "restart",
        "-s", $ServiceName,
        "-y",
        "--json"
    ) | Out-Null

    $restoredDownloadRoot = Join-Path $tempRoot "restored-db"
    $restoredDownloadedDb = Download-RemoteDatabaseSet -TargetDirectory $restoredDownloadRoot -RemotePath $RemoteDatabasePath -LocalFileName "restored.sqlite3"
    $restoredSnapshotValidationPath = Join-Path $tempRoot "restored_snapshot_validation.sqlite3"
    Invoke-PythonHelper -Arguments @(
        "snapshot",
        "--source-db-path", $restoredDownloadedDb,
        "--snapshot-db-path", $restoredSnapshotValidationPath
    ) | Out-Null

    $restoredManifestValidationPath = Join-Path $tempRoot "restored_validation_manifest.json"
    Invoke-PythonHelper -Arguments @(
        "inspect",
        "--db-path", $restoredSnapshotValidationPath,
        "--output-json", $restoredManifestValidationPath,
        "--remote-db-path", $RemoteDatabasePath,
        "--volume-name", $VolumeName,
        "--service-name", $ServiceName,
        "--project-name", $ProjectName,
        "--captured-at", $timestamp.ToString("o"),
        "--require-ok"
    ) | Out-Null
    $restoredManifest = Get-JsonFromFile -Path $restoredManifestValidationPath

    Compare-InspectionResults -ExpectedInspection $selectedManifest.inspection -ActualInspection $restoredManifest.inspection

    [pscustomobject]@{
        restored_archive_path     = $backupArchiveResolved
        pre_restore_archive_path  = $preRestoreArchivePath
        remote_database_path      = $RemoteDatabasePath
        rollback_database_path    = $remoteRollbackPath
        restored_validation       = $restoredManifest.inspection
    } | ConvertTo-Json -Depth 8
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
