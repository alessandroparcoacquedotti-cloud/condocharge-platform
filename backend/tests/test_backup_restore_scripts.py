from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from condocharge.tools.sqlite_backup import build_manifest, inspect_database, write_json


def _create_sample_db(
    path: Path,
    *,
    charging_sessions: int,
    charging_stations: int,
    app_users: int,
    agent_states: int | None = None,
    alembic_version: str = "0018_add_station_agent_state_fields",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE charging_sessions (id INTEGER PRIMARY KEY);")
        conn.execute("CREATE TABLE charging_stations (id INTEGER PRIMARY KEY);")
        conn.execute("CREATE TABLE app_users (id INTEGER PRIMARY KEY);")
        if agent_states is not None:
            conn.execute("CREATE TABLE agent_states (id INTEGER PRIMARY KEY);")
        conn.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL);")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES (?);", (alembic_version,))

        conn.executemany("INSERT INTO charging_sessions DEFAULT VALUES;", [tuple()] * charging_sessions)
        conn.executemany("INSERT INTO charging_stations DEFAULT VALUES;", [tuple()] * charging_stations)
        conn.executemany("INSERT INTO app_users DEFAULT VALUES;", [tuple()] * app_users)
        if agent_states is not None:
            conn.executemany("INSERT INTO agent_states DEFAULT VALUES;", [tuple()] * agent_states)
        conn.commit()


def _write_fake_railway_cli(script_path: Path) -> None:
    script_path.write_text(
        """
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$volumeRoot = $env:FAKE_RAILWAY_VOLUME_ROOT
$stateRoot = $env:FAKE_RAILWAY_STATE_ROOT
if (-not $volumeRoot) { throw "FAKE_RAILWAY_VOLUME_ROOT is required" }
if (-not $stateRoot) { throw "FAKE_RAILWAY_STATE_ROOT is required" }
New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null

function Get-ArgumentValue {
    param([string[]]$Arguments, [string]$Name)
    for ($i = 0; $i -lt $Arguments.Length; $i++) {
        if ($Arguments[$i] -eq $Name) {
            return $Arguments[$i + 1]
        }
    }
    return $null
}

function Get-Positionals {
    param([string[]]$Arguments)
    $positionals = @()
    for ($i = 0; $i -lt $Arguments.Length; $i++) {
        $arg = $Arguments[$i]
        switch ($arg) {
            "--volume" { $i++; continue }
            "--service" { $i++; continue }
            "--concurrency" { $i++; continue }
            "--json" { continue }
            "--overwrite" { continue }
            "--override" { continue }
            "--yes" { continue }
            "-y" { continue }
            "-s" { $i++; continue }
            default { $positionals += $arg }
        }
    }
    return $positionals
}

function Resolve-RemotePath {
    param([string]$RemotePath)
    $trimmed = $RemotePath.TrimStart("/").Replace("/", [IO.Path]::DirectorySeparatorChar)
    return Join-Path $volumeRoot $trimmed
}

function Move-RemoteFile {
    param(
        [string]$SourcePath,
        [string]$DestinationPath
    )

    try {
        Move-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
        return
    }
    catch [System.IO.IOException] {
        # On Windows, renaming a SQLite file inside the same PowerShell process can fail
        # even though a copy+delete swap works. Fall back to that behavior to emulate the
        # remote Railway volume operation more reliably in tests.
        Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
        for ($attempt = 1; $attempt -le 20; $attempt++) {
            try {
                Remove-Item -LiteralPath $SourcePath -Force -ErrorAction Stop
                return
            }
            catch [System.IO.IOException] {
                if ($attempt -eq 20) {
                    return
                }
                Start-Sleep -Milliseconds (100 * $attempt)
            }
        }
    }
}

if ($CliArgs.Length -lt 2) {
    throw "Unsupported fake Railway invocation: $($CliArgs -join ' ')"
}

if ($CliArgs[0] -eq "volume" -and $CliArgs[1] -eq "files") {
    $operation = $CliArgs[2]
    $positionals = Get-Positionals -Arguments $CliArgs[3..($CliArgs.Length - 1)]

    switch ($operation) {
        "download" {
            $remotePath = Resolve-RemotePath $positionals[0]
            $localPath = $positionals[1]
            if (-not (Test-Path -LiteralPath $remotePath)) {
                [Console]::Error.WriteLine("Remote file not found: $remotePath")
                exit 1
            }
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $localPath) | Out-Null
            Copy-Item -LiteralPath $remotePath -Destination $localPath -Force
            Write-Output '{"ok":true}'
            exit 0
        }
        "upload" {
            $localPath = $positionals[0]
            $remotePath = Resolve-RemotePath $positionals[1]
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $remotePath) | Out-Null
            Copy-Item -LiteralPath $localPath -Destination $remotePath -Force
            Write-Output '{"ok":true}'
            exit 0
        }
        "rename" {
            $oldPath = Resolve-RemotePath $positionals[0]
            $newPath = Resolve-RemotePath $positionals[1]
            if (-not (Test-Path -LiteralPath $oldPath)) {
                [Console]::Error.WriteLine("Remote file not found: $oldPath")
                exit 1
            }
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $newPath) | Out-Null
            Move-RemoteFile -SourcePath $oldPath -DestinationPath $newPath
            Write-Output '{"ok":true}'
            exit 0
        }
        "delete" {
            $remotePath = Resolve-RemotePath $positionals[0]
            if (-not (Test-Path -LiteralPath $remotePath)) {
                [Console]::Error.WriteLine("Remote file not found: $remotePath")
                exit 1
            }
            Remove-Item -LiteralPath $remotePath -Force
            Write-Output '{"ok":true}'
            exit 0
        }
        default {
            throw "Unsupported fake Railway volume files operation: $operation"
        }
    }
}

if ($CliArgs[0] -eq "service" -and $CliArgs[1] -eq "restart") {
    $restartFile = Join-Path $stateRoot "restart-count.txt"
    $currentValue = 0
    if (Test-Path -LiteralPath $restartFile) {
        $currentValue = [int](Get-Content -LiteralPath $restartFile -Raw)
    }
    Set-Content -LiteralPath $restartFile -Value ($currentValue + 1)
    Write-Output '{"ok":true}'
    exit 0
}

throw "Unsupported fake Railway invocation: $($CliArgs -join ' ')"
""".strip(),
        encoding="utf-8",
    )


def _run_powershell_script(
    script_path: Path,
    *,
    backend_root: Path,
    railway_command: Path,
    backup_root: Path,
    extra_args: list[str] | None = None,
    state_root: Path,
    volume_root: Path,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend_root / "src")
    env["FAKE_RAILWAY_VOLUME_ROOT"] = str(volume_root)
    env["FAKE_RAILWAY_STATE_ROOT"] = str(state_root)

    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if pwsh is None:
        raise RuntimeError("PowerShell executable not found (expected pwsh or powershell)")

    command = [
        pwsh,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-RailwayCommand",
        str(railway_command),
        "-PythonCommand",
        sys.executable,
        "-BackupRoot",
        str(backup_root),
    ]
    if extra_args:
        command.extend(extra_args)

    return subprocess.run(
        command,
        cwd=backend_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _create_restore_archive(archive_path: Path, db_path: Path) -> None:
    manifest = build_manifest(
        db_path=db_path,
        remote_db_path="/data/pilot_real.sqlite3",
        volume_name="condocharge-prod-volume",
        service_name="condocharge-prod",
        project_name="natural-curiosity",
        captured_at_utc=datetime.now(tz=UTC).isoformat(),
    )
    manifest_path = archive_path.with_suffix(".manifest.json")
    write_json(manifest_path, manifest)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(db_path, arcname="backup_snapshot.sqlite3")
        archive.write(manifest_path, arcname="backup_manifest.json")


def test_backup_database_script_creates_archive(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    volume_root = tmp_path / "volume"
    state_root = tmp_path / "state"
    fake_railway = tmp_path / "fake_railway.ps1"
    _write_fake_railway_cli(fake_railway)

    remote_db_path = volume_root / "data" / "pilot_real.sqlite3"
    _create_sample_db(remote_db_path, charging_sessions=5, charging_stations=2, app_users=4)

    backup_root = tmp_path / "backups"
    result = _run_powershell_script(
        backend_root / "backup_database.ps1",
        backend_root=backend_root,
        railway_command=fake_railway,
        backup_root=backup_root,
        state_root=state_root,
        volume_root=volume_root,
        extra_args=["-TimestampUtc", "2026-06-15T00:00:00Z"],
    )

    assert result.returncode == 0, result.stderr or result.stdout
    daily_archives = sorted((backup_root / "daily").glob("*.zip"))
    assert len(daily_archives) == 1
    manifest_path = next((backup_root / "daily").glob("*.manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["inspection"]["integrity_check"] == "ok"
    assert manifest["inspection"]["row_counts"]["charging_sessions"] == 5
    assert manifest["inspection"]["row_counts"]["charging_stations"] == 2
    assert manifest["inspection"]["row_counts"]["app_users"] == 4
    assert manifest["inspection"]["row_counts"]["agent_states"] is None

    with zipfile.ZipFile(daily_archives[0]) as archive:
        assert set(archive.namelist()) == {"backup_manifest.json", "backup_snapshot.sqlite3"}


def test_restore_database_script_restores_selected_backup(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    volume_root = tmp_path / "volume"
    state_root = tmp_path / "state"
    fake_railway = tmp_path / "fake_railway.ps1"
    _write_fake_railway_cli(fake_railway)

    remote_db_path = volume_root / "data" / "pilot_real.sqlite3"
    _create_sample_db(remote_db_path, charging_sessions=3, charging_stations=2, app_users=4)

    restore_source_db = tmp_path / "restore_source.sqlite3"
    _create_sample_db(
        restore_source_db,
        charging_sessions=9,
        charging_stations=2,
        app_users=5,
        agent_states=1,
        alembic_version="0019_create_agent_states",
    )

    backup_root = tmp_path / "backups"
    restore_archive = tmp_path / "selected_restore.zip"
    _create_restore_archive(restore_archive, restore_source_db)

    result = _run_powershell_script(
        backend_root / "restore_database.ps1",
        backend_root=backend_root,
        railway_command=fake_railway,
        backup_root=backup_root,
        state_root=state_root,
        volume_root=volume_root,
        extra_args=["-BackupArchivePath", str(restore_archive), "-TimestampUtc", "2026-06-18T15:00:00Z"],
    )

    assert result.returncode == 0, result.stderr or result.stdout
    restored = inspect_database(remote_db_path)
    assert restored.integrity_check == "ok"
    assert restored.row_counts["charging_sessions"] == 9
    assert restored.row_counts["charging_stations"] == 2
    assert restored.row_counts["app_users"] == 5
    assert restored.row_counts["agent_states"] == 1
    assert restored.alembic_version == "0019_create_agent_states"

    restart_count = int((state_root / "restart-count.txt").read_text(encoding="utf-8").strip())
    assert restart_count == 1
    assert len(list((backup_root / "pre-restore").glob("*.zip"))) == 1


def test_backup_database_script_fails_integrity_validation_for_invalid_db(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    volume_root = tmp_path / "volume"
    state_root = tmp_path / "state"
    fake_railway = tmp_path / "fake_railway.ps1"
    _write_fake_railway_cli(fake_railway)

    invalid_db_path = volume_root / "data" / "pilot_real.sqlite3"
    invalid_db_path.parent.mkdir(parents=True, exist_ok=True)
    invalid_db_path.write_text("not-a-valid-sqlite-db", encoding="utf-8")

    backup_root = tmp_path / "backups"
    result = _run_powershell_script(
        backend_root / "backup_database.ps1",
        backend_root=backend_root,
        railway_command=fake_railway,
        backup_root=backup_root,
        state_root=state_root,
        volume_root=volume_root,
        extra_args=["-TimestampUtc", "2026-06-15T00:00:00Z"],
    )

    assert result.returncode != 0
    assert "Command failed" in result.stderr or "database" in result.stderr.lower() or "database" in result.stdout.lower()


def test_backup_database_script_applies_retention_policy(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    volume_root = tmp_path / "volume"
    state_root = tmp_path / "state"
    fake_railway = tmp_path / "fake_railway.ps1"
    _write_fake_railway_cli(fake_railway)

    remote_db_path = volume_root / "data" / "pilot_real.sqlite3"
    _create_sample_db(remote_db_path, charging_sessions=2, charging_stations=2, app_users=4)
    backup_root = tmp_path / "backups"

    for day_index in range(8):
        day = datetime(2026, 6, 8, tzinfo=UTC) + timedelta(days=day_index)
        result = _run_powershell_script(
            backend_root / "backup_database.ps1",
            backend_root=backend_root,
            railway_command=fake_railway,
            backup_root=backup_root,
            state_root=state_root,
            volume_root=volume_root,
            extra_args=["-TimestampUtc", day.isoformat()],
        )
        assert result.returncode == 0, result.stderr or result.stdout

    for week_index in range(5):
        sunday = datetime(2026, 6, 7, tzinfo=UTC) + timedelta(days=7 * week_index)
        result = _run_powershell_script(
            backend_root / "backup_database.ps1",
            backend_root=backend_root,
            railway_command=fake_railway,
            backup_root=backup_root,
            state_root=state_root,
            volume_root=volume_root,
            extra_args=["-TimestampUtc", sunday.isoformat()],
        )
        assert result.returncode == 0, result.stderr or result.stdout

    for month_index in range(7):
        month = datetime(2026, 1 + month_index, 1, tzinfo=UTC)
        result = _run_powershell_script(
            backend_root / "backup_database.ps1",
            backend_root=backend_root,
            railway_command=fake_railway,
            backup_root=backup_root,
            state_root=state_root,
            volume_root=volume_root,
            extra_args=["-TimestampUtc", month.isoformat()],
        )
        assert result.returncode == 0, result.stderr or result.stdout

    assert len(list((backup_root / "daily").glob("*.zip"))) == 7
    assert len(list((backup_root / "weekly").glob("*.zip"))) == 4
    assert len(list((backup_root / "monthly").glob("*.zip"))) == 6
