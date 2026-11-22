# Windows packaging runbook

Everything in this directory must run on a Windows build machine with
Python 3.12, Inno Setup 6, and the desktop requirements installed.

## 1. Provision the embedded public key

The EXE must embed ONLY the public verification key:

```
python scripts\generate_signing_keys.py ^
    --server-keys-dir C:\secure\keys ^
    --desktop-pub desktop\security\public_keys\cloud_ed25519.pub
```

(If keys already exist on the release server, run the same command against
the existing keys dir — the tool refuses to overwrite existing keys.)

## 2. Icon

`scripts\build\icon.ico` is committed; regenerate any time with
`python scripts\make_icon.py` (needs Pillow).

## 3. Build the EXE

```
pip install -r requirements-desktop.txt
pyinstaller desktop\packaging\grocery_erp_pro.spec --noconfirm
```

Output: `dist\GroceryERPPro.exe` (one-file, windowed). The spec collects the
SQL migration scripts and the embedded public key as data files, sets the
icon + VERSIONINFO, and excludes web/test frameworks.

**Verify the packaged EXE before release** (rule 26 — an untested EXE must
not be distributed):

1. Launch on Windows 10 and 11; confirm the DB was created under
   `%LOCALAPPDATA%\GroceryERPPro\` (NOT next to the EXE).
2. Make a sale offline; check the outbox row exists.
3. Block network, restart the EXE, sell again; go online; confirm the ack.
4. Upgrade the EXE from 1.0.0 to the next version; verify the DB and all
   pending outbox events survive; verify `schema_migrations` advanced.
5. Run the Update Center against a staged release; interrupt the download
   midway and resume; verify the checksum gate catches a corrupted package.

## 4. Build the installer

```
iscc desktop\packaging\installer.iss
```

Output: `desktop\packaging\dist\GroceryERPPro-Setup-1.0.0.exe`.

The installer replaces only program files; the data directory is never
touched, and uninstalling keeps all local data (empty `[UninstallDelete]`).

## 5. Publish the release

Upload the installer/patch package via
`POST /api/v1/updates/releases/publish/` as a platform administrator; the
server signs the manifest with its Ed25519 key. Deploy to `internal`
first, then `beta`, then `stable`; pause or withdraw via the manage API on
failure.
