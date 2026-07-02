#!/usr/bin/env pwsh
# pm2-safe-restart.ps1
# Safe PM2 restart for llull-api from non-interactive/exec contexts.
#
# ROOT CAUSE: On Windows, pm2 uses \\.\pipe\rpc.sock with ACL tied to the daemon's
# security context. When exec/subagent processes call `pm2 restart`, they get EPERM
# connecting to the pipe. PM2 misinterprets EPERM as "no daemon running" and spawns
# a new daemon, which also can't bind the pipe (already owned). This leaves zombie
# daemon processes accumulating on every failed call.
#
# FIX (Option C): Never call `pm2 restart` from automated/exec contexts.
# Instead: kill the uvicorn process directly — PM2 detects the exit and auto-restarts it.

param(
    [string]$AppName = "llull-api"
)

Write-Host "Safe-restarting PM2 app: $AppName"

# Find the process by matching the pm2 dump exec path pattern
$dumpPath = "$env:USERPROFILE\.pm2\dump.pm2"
$execPath = $null

if (Test-Path $dumpPath) {
    $dump = Get-Content $dumpPath -Raw
    # Simple regex to find exec_path for our app
    if ($dump -match """name""\s*:\s*""$AppName""[\s\S]*?""pm_exec_path""\s*:\s*""([^""]+)""") {
        $execPath = $Matches[1] -replace '\\\\', '\'
        Write-Host "Found exec path: $execPath"
    }
}

# Find running process matching llull-api patterns
$targetProcs = Get-Process -Name "uvicorn","python","python3" -ErrorAction SilentlyContinue | ForEach-Object {
    $procPid = $_.Id
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$procPid" -ErrorAction SilentlyContinue).CommandLine
    if ($cmd -match "uvicorn" -and $cmd -match "llull|app\.main") {
        [PSCustomObject]@{ Proc = $_; Cmd = $cmd }
    }
} | Where-Object { $_ }

if (-not $targetProcs) {
    Write-Host "No running $AppName process found — PM2 will start it on next cycle."
    exit 0
}

foreach ($t in $targetProcs) {
    Write-Host "Killing PID $($t.Proc.Id): $($t.Cmd.Substring(0, [Math]::Min(80, $t.Cmd.Length)))..."
    Stop-Process -Id $t.Proc.Id -Force
}

Write-Host "Done. PM2 will auto-restart $AppName within 3 seconds."
