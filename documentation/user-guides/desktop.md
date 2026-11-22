# Desktop quick guide

- First launch: the app creates its own database under
  `%LOCALAPPDATA%\GroceryERPPro\` (independently per installation), applies
  schema migrations, and generates a device identity.
- POS: scan/enter barcode or search, adjust quantity, press `Ctrl+Enter`
  (or the on-screen commit action) to commit. The sale commits locally
  first; the status bar shows "saved locally" until the cloud ack arrives
  (then "confirmed by cloud").
- Sync: a background worker drains the outbox when connectivity allows —
  it never blocks the POS. Status shows pending/failed/conflict counts.
- Update Center: check, verify signed metadata, resumable download,
  checksum verify, pre-install report, staged install (data directory is
  never touched).
- Backups: local SQLite backup/restore in the app; verify restores
  regularly. Backups require no internet.
