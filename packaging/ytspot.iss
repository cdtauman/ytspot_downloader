; Inno Setup script for YTSpot Downloader
; Compile with: iscc packaging\ytspot.iss
; (Inno Setup 6 is free: https://jrsoftware.org/isdl.php)
;
; Run scripts/build_windows.ps1 BEFORE compiling this installer — it
; produces the dist/ytspot/ folder that the installer packages.

#define AppName        "YTSpot Downloader"
#define AppPublisher   "Tauman Software"
#define AppURL         "https://github.com/cdtauman-projects/ytspot_downloader"
#define AppExeName     "ytspot.exe"
#define AppCliExeName  "ytspot-cli.exe"
#define AppId          "{{6B3F2DAE-6F11-4B0D-8B5E-3B5C7D7E8F90}}"

; Read the version from packaging/version_info.txt so a single bump in
; version.py propagates here too. ISPP supports GetStringFileInfo on
; the EXE we just built — that is the most robust path.
#define AppVersion GetStringFileInfo("..\dist\ytspot\ytspot.exe", "ProductVersion")

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=ytspot-{#AppVersion}-windows-setup
SetupIconFile=ytspot.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\THIRD_PARTY_NOTICES.md

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "hebrew";  MessagesFile: "compiler:Languages\Hebrew.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "installplaywright"; Description: "Install Playwright Chromium (~300 MB) for channel scraping and sign-in wizard"; Flags: unchecked

[Files]
; Bundle the entire one-folder PyInstaller dist.
Source: "..\dist\ytspot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Helper scripts so the user can re-run them post-install.
Source: "..\scripts\install_playwright.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
; Notices and release doc.
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md";              DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{#AppName} (CLI)"; Filename: "{app}\{#AppCliExeName}"
Name: "{group}\Install Playwright"; Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\scripts\install_playwright.ps1"""
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Optional: install Playwright at the end of setup if the user ticked it.
Filename: "powershell.exe"; \
    Parameters: "-ExecutionPolicy Bypass -File ""{app}\scripts\install_playwright.ps1"""; \
    StatusMsg: "Installing Playwright Chromium..."; \
    Tasks: installplaywright; Flags: runhidden
; Launch the app at the end of setup if the user wants to.
Filename: "{app}\{#AppExeName}"; \
    Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Do not delete the user's downloads or their ~/.ytspot config — only
; remove files we installed. ~/.ytspot lives under %APPDATA% which is
; out of {app} so it survives uninstall by default.
Type: filesandordirs; Name: "{app}\scripts"
