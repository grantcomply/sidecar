; Inno Setup script for Serato Sidecar (Windows installer).
;
; Builds a standard Program Files installer from the one-folder PyInstaller
; output at dist\SeratoSidecar\. Compile with:
;
;     ISCC.exe build\installer.iss
;
; Output: build\output\SeratoSidecar-Setup-0.1.0.exe
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
#define MyAppName "Serato Sidecar"
#define MyAppExeName "SeratoSidecar.exe"
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
DefaultDirName={autopf}\SeratoSidecar
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=SeratoSidecar-Setup-{#MyAppVersion}
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

[Files]
; Source paths are resolved relative to the .iss file's directory
; (i.e. build\installer.iss → repo\build\), so we climb one level up
; to pick up the PyInstaller output in dist\SeratoSidecar\.
Source: "..\dist\SeratoSidecar\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\SeratoSidecar\*"; DestDir: "{app}"; Excludes: "{#MyAppExeName}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
