; Inno Setup script for Sidecar (Windows installer).
;
; Builds a standard Program Files installer from the one-folder PyInstaller
; output at dist\DJSidecar\. Compile with:
;
;     ISCC.exe build\installer.iss
;
; Output: build\output\DJSidecar-Setup-0.1.0.exe
;
; Phase 2 of plans/deployment-plan.md. The version string is hard-coded for
; now; Phase 3's GHA workflow will substitute it from source\__version__.py
; before invoking ISCC.

; MyAppVersion can be overridden from the command line via
;     ISCC.exe /DMyAppVersion=1.2.3 build\installer.iss
; which is exactly what the GitHub Actions release workflow does (see
; .github/workflows/release.yml) after deriving the version from the pushed
; tag. The #ifndef guard below is load-bearing: Inno Setup's #define will
; NOT overwrite an existing definition, so the /D on the command line only
; takes effect if we skip the fallback when the variable is already set.
#define MyAppName "Sidecar"
#define MyAppExeName "DJSidecar.exe"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#define MyAppPublisher "Grant"
#define MyAppURL "https://example.com/todo-set-real-url"

[Setup]
; AppId uniquely identifies this application for Inno Setup's upgrade /
; uninstall bookkeeping. Do NOT change it across releases.
AppId={{6D3C2E3E-9A4F-4F4A-9B56-3B8A7D1A0F11}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\DJSidecar
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=DJSidecar-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Upgrades from v0.1.6 and earlier (same AppId, so Inno reuses the old
; install dir): the exe was SeratoSidecar.exe and the shortcuts were named
; "Serato Sidecar". Remove them so the user doesn't keep a stale exe and
; duplicate Start-menu / desktop entries next to the new "Sidecar" ones.
Type: files; Name: "{app}\SeratoSidecar.exe"
Type: files; Name: "{autoprograms}\Serato Sidecar.lnk"
Type: files; Name: "{autodesktop}\Serato Sidecar.lnk"

[Files]
; Source paths are resolved relative to the .iss file's directory
; (i.e. build\installer.iss → repo\build\), so we climb one level up
; to pick up the PyInstaller output in dist\DJSidecar\.
Source: "..\dist\DJSidecar\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\DJSidecar\*"; DestDir: "{app}"; Excludes: "{#MyAppExeName}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
