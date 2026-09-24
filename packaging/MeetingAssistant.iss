#define MyAppName "Meeting Assistant"
#define MyAppPublisher "Meeting Assistant"
#define MyAppURL "https://github.com/eduardoveiga-py/meeting-assistant"
#define MyAppExeName "MeetingAssistant.exe"
#ifndef MyAppVersion
  #error MyAppVersion must be supplied by scripts/build-windows.ps1
#endif

[Setup]
AppId={{E23B3DD7-1D83-4BD0-AF6E-1A5E27DD98F1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\Meeting Assistant
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir={#SourcePath}..\release
OutputBaseFilename=MeetingAssistant-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes

[Languages]
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Files]
Source: "{#SourcePath}..\dist\MeetingAssistant\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourcePath}..\README.md"; DestDir: "{app}\documentation"; Flags: ignoreversion
Source: "{#SourcePath}..\CHANGELOG.md"; DestDir: "{app}\documentation"; Flags: ignoreversion
Source: "{#SourcePath}..\docs\operator-guide.md"; DestDir: "{app}\documentation"; Flags: ignoreversion
Source: "{#SourcePath}..\docs\installation.md"; DestDir: "{app}\documentation"; Flags: ignoreversion
Source: "{#SourcePath}..\docs\recovery-and-updates.md"; DestDir: "{app}\documentation"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent
