# PM2 on Windows — Daemon Multiplicity Bug & Fix

## Root Cause

On Windows, PM2 uses a named pipe `\\.\pipe\rpc.sock` to communicate between the
CLI and the daemon. The ACL on this pipe is tied to the **security context of the
process that created the daemon** (typically the interactive user session).

When `pm2 restart/status/list` is called from a **non-interactive context** (exec,
subagent, cron, CI), the process gets `EPERM` trying to connect to the pipe.

PM2 misinterprets `EPERM` as "no daemon running" (should be `ECONNREFUSED`), and:
1. Spawns a **new daemon** 
2. The new daemon also can't bind `rpc.sock` (already owned) — it becomes a zombie
3. The CLI process exits with an error, leaving the zombie daemon alive

**Result:** every failed `pm2 restart` from exec adds one zombie node process.

## Rule

> **Never call `pm2 restart`, `pm2 reload`, or `pm2 start` from exec/automated contexts.**

This includes: OpenClaw exec tool, subagent sessions, cron jobs, PowerShell scripts
called from non-interactive sessions.

## Safe Alternatives

### Restart llull-api (from exec/scripts)
```powershell
# Kill uvicorn directly — PM2 auto-restarts it within 3s
powershell -File C:\workspace\repos\llull\scripts\pm2-safe-restart.ps1
```

### Check if llull-api is running (from exec)
```powershell
# Check the process directly — don't call pm2 list
Get-Process -Name "uvicorn" -ErrorAction SilentlyContinue | Where-Object {
    (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine -match "llull"
}
```

### Restart from interactive terminal (OK)
```powershell
pm2 restart llull-api   # Fine from your own terminal
pm2 resurrect           # Fine from your own terminal
```

## Cleaning Up Zombie Daemons

If zombie daemons accumulate, run from your terminal:
```powershell
pm2 kill       # Stops the legit daemon + all managed processes
pm2 resurrect  # Restores all processes from dump.pm2
```

This kills ALL node daemons (including zombies since they share the same process name).
After `resurrect`, only one clean daemon runs.

## Detection

Count zombie daemons:
```powershell
Get-Process -Name "node" | Where-Object {
    (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine -match "pm2.*Daemon"
} | Measure-Object | Select-Object -ExpandProperty Count
```

Healthy state: count = 1.
