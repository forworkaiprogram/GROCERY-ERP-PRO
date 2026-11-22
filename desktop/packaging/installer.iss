; Inno Setup script for GROCERY ERP PRO.
; Requires Inno Setup 6 on Windows. Build:
;   iscc desktop\packaging\installer.iss
;
; Safety properties (per product requirements):
;  - never touches %LOCALAPPDATA%\GroceryERPPro (the persistent data dir)
;  - uninstall keeps local database files by default
;  - upgrade-in-place replaces only the program files

#define AppName "GROCERY ERP PRO"
#define AppExe "GroceryERPPro.exe"
#define AppVersion "1.0.0"
#define AppPublisher "Grocery ERP Pro"
#define AppDir "GroceryERPPro"

[Setup]
AppId={{7C1A5E9F-2E44-4B8B-9A57-GROCERYERP01}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppDir}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=GroceryERPPro-Setup-{#AppVersion}
OutputDir=dist
LicenseFile=..\..\LICENSE

[Files]
Source: "..\dist-gui\GroceryERPPro\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Deliberately EMPTY: uninstall must never delete the persistent data
; directory (%LOCALAPPDATA%\GroceryERPPro), local databases, backups, or
; pending outbox events. Data removal is an explicitly authorized,
; documented manual process.
