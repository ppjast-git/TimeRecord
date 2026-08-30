; TimeRecord — Inno Setup script
; Kompiluj: ISCC.exe installer.iss
; Lub przez: python scripts/build.py
;
; Instalacja per-user (%LOCALAPPDATA%\Programs\TimeRecord) — bez uprawnień admina.

#define MyAppName "TimeRecord"
#define MyAppPublisher "TimeRecord"
#define MyAppExeName "TimeRecord.exe"
#define MyAppVersion "0.2.1"
#define MyAppURL "https://github.com/ppjast-git/TimeRecord"

[Setup]
AppId={{TimeRecord-App-ID-2026}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=TimeRecord-Setup-v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
; Nie restartuj — nie potrzebne
RestartIfNeededByRun=no

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "autostart"; Description: "Uruchom z systemem (autostart)"; GroupDescription: "Opcje:"; Flags: checkedonce

[Files]
; Główny folder z buildu PyInstaller (dist/TimeRecord/*)
Source: "dist\TimeRecord\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Skrót w Menu Start
Name: "{group}\TimeRecord"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\Odinstaluj TimeRecord"; Filename: "{uninstallexe}"

; Skrót na pulpicie (opcjonalny)
Name: "{autodesktop}\TimeRecord"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: autostart

; Skrót autostartu (shell:startup)
Name: "{userstartup}\TimeRecord"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: autostart

[Run]
; Uruchom po instalacji (opcjonalnie w kreatorze; zawsze po cichej aktualizacji)
Filename: "{app}\{#MyAppExeName}"; Description: "Uruchom TimeRecord teraz"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Zabij proces przed odinstalowaniem
Filename: "{cmd}"; Parameters: "/C taskkill /IM {#MyAppExeName} /F /T"; Flags: runhidden; RunOnceId: "KillApp"

[UninstallDelete]
; Usuń folder aplikacji całkowicie
Type: filesandordirs; Name: "{app}"

[Code]
// Zabij działający proces TimeRecord PRZED instalacją (dla upgrade)
// Bez tego instalator nie może nadpisać TimeRecord.exe (plik zajęty).
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // taskkill /IM TimeRecord.exe /F — ciche, ignoruj błędy (proces może nie działać)
  Exec(ExpandConstant('{cmd}'), '/C taskkill /IM {#MyAppExeName} /F /T', '',
       SW_HIDE, ewWaitUntilTerminated, ResultCode);
  // Krótka pauza by system zwolnił plik
  Sleep(500);
  Result := True;
end;
