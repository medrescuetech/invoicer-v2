---
name: testing-invoicer-desktop
description: How to run and GUI-test the Invoicer V2 PySide6 desktop app end-to-end on Windows (data dir isolation, launching, logs, single-instance lock).
---

# Testing the Invoicer V2 desktop app (Windows / PySide6)

## Environment
- The shell is **PowerShell** - use `;` between commands, `&&` is invalid.
- A ready `.venv` exists in the repo root; run everything with `.venv\Scripts\python.exe`.
- Entry point: `.venv\Scripts\python.exe -m invoice_manager` from the repo root.
- Checks: `.venv\Scripts\ruff.exe check .`, `.venv\Scripts\ruff.exe format --check .`,
  `.venv\Scripts\mypy.exe src\invoice_manager`, `.venv\Scripts\python.exe -m pytest`.
  Warnings are configured as errors, so a new DeprecationWarning fails the suite.

## Isolate the data directory (never touch the real one)
`AppPaths.resolve()` (`src/invoice_manager/config.py`) reads `INVOICER_DATA_DIR`, defaulting to
`%USERPROFILE%\InvoiceReceiptManager`. Always point it at a throwaway path and delete it first to
exercise the true first-run path:

```powershell
$env:INVOICER_DATA_DIR="C:\Users\Administrator\invoicer-e2e"
Remove-Item -Recurse -Force $env:INVOICER_DATA_DIR -ErrorAction SilentlyContinue
Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "-m","invoice_manager" `
  -WorkingDirectory "C:\Users\Administrator\repos\invoicer-v2"
```
Env vars set with `$env:` only apply to processes started from that same shell call, so set the var
and `Start-Process` in one `exec` invocation.

## Getting the GUI on screen
- Qt dialogs open *behind* whatever is focused (e.g. Chrome). Minimize everything first
  (`Win+D`) before recording, otherwise the app is invisible in screenshots.
- Enumerate top-level windows to confirm a dialog exists (useful when it is hidden):
  `Get-Process python | Select-Object Id,MainWindowTitle` shows titles such as
  `Invoicer V2 - Create administrator` / `- Sign in`.
- Double-click the title bar to maximize; the status bar (`Signed in: <name>`) is otherwise clipped
  by the taskbar.

## First-run / login flow
1. Fresh DB -> Alembic upgrade runs (console prints `Running upgrade -> 0001_initial`) -> "Create
   administrator" dialog (Username / Display name / Password). There is no default password.
2. After creating the admin, the "Sign in" dialog appears in the same process.
3. Failed login shows a red in-dialog label "Invalid username or password." The message is
   deliberately identical for a wrong password and an unknown username - do not "improve" it into
   something that reveals whether the username exists.

## App Log viewer
- The app logs lifecycle events (startup, data location, migration, login success/failure,
  single-instance refusal, shutdown) to `logs/app.log`, so the viewer has real content after a run.
  Credentials are never logged.
- The dialog reads the file on each change, so **Refresh** picks up externally written lines. Level
  filtering matches `" <LEVEL> "` in the raw line.

## Single-instance lock
- `data\invoicer.lock` holds the owning PID. A second launch while the first is alive shows a
  critical box "another Invoicer V2 instance is already running" and exits 1.
- A lock left behind by a killed process is reclaimed automatically (the PID is checked for
  liveness), so a crash no longer blocks startup. If you change this code, test both cases: stale
  lock reclaimed, live lock refused.

## Useful DB check
```powershell
.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect(r'<datadir>\data\business.sqlite3'); print(c.execute('select id,username,display_name,substr(password_hash,1,30),last_login_at from users').fetchall())"
```
Hashes must start with `$argon2id$`, and `last_login_at` is populated after a successful login.

## Devin secrets needed
None - the app is fully local.
