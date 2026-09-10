# Installation Guide — Invoice & Receipt Manager v2

## System requirements

- Windows 10 or Windows 11 (64-bit)
- Approximately 150 MB free disk space for the installer
- An additional 50–200 MB over time for the local SQLite database, PDFs, and logs

## Install with the setup wizard

1. Download `InvoiceReceiptManager_{version}_Setup.exe` from the `dist` folder or the latest release.
2. Double-click the installer.
3. Follow the prompts. The default install location is:

   ```
   C:\Program Files\Invoice & Receipt Manager
   ```

4. The installer creates:
   - A **Start Menu** program group
   - An optional **Desktop shortcut** (if selected in the wizard)
5. Launch the application from the Start Menu or desktop shortcut.

## Run the portable executable

If you prefer not to install, use the standalone executable:

```
dist\InvoiceReceiptManager-2.0.8.exe
```

By default the executable stores data, documents, and logs in `%LOCALAPPDATA%\InvoiceReceiptManager`. To make it store data next to the executable, create or place a `data` folder in the same directory as the `.exe` before running it. The application will then use that folder instead of `%LOCALAPPDATA%`.

## Use the portable zip

A ready-to-go portable archive is also available:

```
dist\InvoiceReceiptManager_2.0.8_Portable.zip
```

To move the whole program and all your data to another location:

1. Close the application.
2. Extract `InvoiceReceiptManager_2.0.8_Portable.zip` to the desired folder (for example, a OneDrive or USB folder).
3. The archive contains the `.exe` plus the full data tree (`data/`, `documents/`, `exports/`, `backups/`, `logs/`, and `config.json`).
4. Run `InvoiceReceiptManager-2.0.8.exe` from that folder. It will use the local data automatically.

## First run

On the first run the application will:

- Create a local data directory at `%LOCALAPPDATA%\InvoiceReceiptManager`
- Create the SQLite database, default settings, and `logs` folder
- Show the login dialog with the default admin account (set up on first run)

## Data and backups

- **Database:** `%LOCALAPPDATA%\InvoiceReceiptManager\data\business.sqlite3` (or `data\business.sqlite3` next to the `.exe` in portable mode)
- **Documents:** `%LOCALAPPDATA%\InvoiceReceiptManager\documents\invoices`, `quotes`, `receipts`, `statements` (or `documents\...` next to the `.exe` in portable mode)
- **Logs:** `%LOCALAPPDATA%\InvoiceReceiptManager\logs` (or `logs\` next to the `.exe` in portable mode)
- **Settings:** `%LOCALAPPDATA%\InvoiceReceiptManager\config.json` (or `config.json` next to the `.exe` in portable mode)

Use **Tools > Backup now** to create a timestamped ZIP of this data. Store backups somewhere other than the install location, preferably in OneDrive or another safe location.

## Upgrading

1. Create a backup via **Tools > Backup now**.
2. Run the new `InvoiceReceiptManager_{version}_Setup.exe`. The installer will overwrite the program files but will not touch your data directory.
3. Launch the application and verify your data is present.

## Uninstalling

Use **Windows Settings > Apps > Invoice & Receipt Manager > Uninstall**. This removes the program files only. Your data in `%LOCALAPPDATA%\InvoiceReceiptManager` is left in place and must be removed manually if desired.

## Troubleshooting

- **Only one instance can run at a time.** If the app does not open, check the Task Manager for a lingering `InvoiceReceiptManager-2.0.8.exe` process.
- **Missing PDFs:** ensure `reportlab` and the application data directory are accessible. PDFs are written to `%LOCALAPPDATA%\InvoiceReceiptManager\documents`.
- **Install error:** run the installer as Administrator if you chose a protected folder such as `C:\Program Files`.
