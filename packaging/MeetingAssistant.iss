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
DefaultDirName={autopf}\Meeting Assistant
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir={#SourcePath}..\release
OutputBaseFilename=MeetingAssistant-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=no
RestartApplications=no
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.22000
DisableProgramGroupPage=yes

[Languages]
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Components]
Name: "app"; Description: "Aplicativo com Python e bibliotecas incluídos"; Types: full compact custom; Flags: fixed
Name: "camera"; Description: "Câmera virtual nativa para Windows 11 / WhatsApp"; Types: full
Name: "bridge"; Description: "Ponte de vídeo do OBS (selecione a pasta do OBS)"; Types: full

[Files]
Source: "{#SourcePath}..\dist\MeetingAssistant\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourcePath}..\README.md"; DestDir: "{app}\documentation"; Flags: ignoreversion
Source: "{#SourcePath}..\CHANGELOG.md"; DestDir: "{app}\documentation"; Flags: ignoreversion
Source: "{#SourcePath}..\docs\operator-guide.md"; DestDir: "{app}\documentation"; Flags: ignoreversion
Source: "{#SourcePath}..\docs\installation.md"; DestDir: "{app}\documentation"; Flags: ignoreversion
Source: "{#SourcePath}..\docs\releases\v{#MyAppVersion}.md"; DestDir: "{app}\documentation"; Flags: ignoreversion
Source: "{#SourcePath}..\build\video-native\package\*"; DestDir: "{app}\native"; Flags: ignoreversion
Source: "{#SourcePath}..\build\prerequisites\vc_redist.x64.exe"; Flags: dontcopy
Source: "{#SourcePath}installer-preflight.ps1"; Flags: dontcopy

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sysnative}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Start-Process -FilePath '{sysnative}\WindowsPowerShell\v1.0\powershell.exe' -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File ''{app}\native\install-video-native.ps1'' -Component RemoveCamera' -Verb RunAs -WindowStyle Hidden -Wait"""; Flags: runhidden
Filename: "{sysnative}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Start-Process -FilePath '{sysnative}\WindowsPowerShell\v1.0\powershell.exe' -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File ''{app}\native\install-video-native.ps1'' -Component RemoveBridge' -Verb RunAs -WindowStyle Hidden -Wait"""; Flags: runhidden

[Code]
var
  ObsPage: TInputDirWizardPage;
  RestartRequired: Boolean;

procedure InitializeWizard;
begin
  ObsPage := CreateInputDirPage(wpSelectComponents, 'Pasta do OBS Studio',
    'Onde o OBS está instalado?',
    'Selecione a pasta que contém bin\64bit\obs64.exe. Se ainda não instalou o OBS, ' +
    'desmarque a ponte na página anterior. Depois use o assistente do aplicativo.', False, '');
  ObsPage.Add('Pasta do OBS:');
  ObsPage.Values[0] := ExpandConstant('{autopf}\obs-studio');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = ObsPage.ID) and not WizardIsComponentSelected('bridge');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = ObsPage.ID) and WizardIsComponentSelected('bridge') then
    if not FileExists(ObsPage.Values[0] + '\bin\64bit\obs64.exe') then begin
      MsgBox('OBS não encontrado nessa pasta. Selecione a pasta correta ou desmarque a ponte.', mbError, MB_OK);
      Result := False;
    end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
begin
  Result := '';
  ExtractTemporaryFile('installer-preflight.ps1');
  if not Exec(ExpandConstant('{sysnative}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\installer-preflight.ps1') + '"',
    '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
    Result := 'Não foi possível verificar os aplicativos abertos.'
  else if ExitCode <> 0 then
    Result := 'Feche Meeting Assistant, OBS, WhatsApp e a câmera virtual antes de instalar. Nenhum processo será encerrado pelo instalador.';
end;

procedure InstallNativeComponent(Component: String);
var
  ExitCode: Integer;
  Parameters: String;
begin
  Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{app}\native\install-video-native.ps1') + '" -Component ' + Component;
  if Component = 'Bridge' then
    Parameters := Parameters + ' -ObsDirectory "' + ObsPage.Values[0] + '"';
  if not ShellExec('runas', ExpandConstant('{sysnative}\WindowsPowerShell\v1.0\powershell.exe'), Parameters,
    ExpandConstant('{app}\native'), SW_SHOW, ewWaitUntilTerminated, ExitCode) then
    MsgBox('Nao foi possivel executar o instalador da camera/ponte.', mbError, MB_OK);
  if ExitCode <> 0 then
    MsgBox('O Windows bloqueou a instalacao de ' + Component + ' (possivel restricao do Smart App Control). O app funcionara normalmente e voce podera tentar instalá-lo depois pelo menu Ajustes.', mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    ExtractTemporaryFile('vc_redist.x64.exe');
    if not Exec(ExpandConstant('{tmp}\vc_redist.x64.exe'), '/install /quiet /norestart',
      '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      RaiseException('Não foi possível instalar o runtime Microsoft Visual C++.');
    if (ExitCode <> 0) and (ExitCode <> 3010) and (ExitCode <> 1638) then
      RaiseException('Runtime Microsoft Visual C++: código ' + IntToStr(ExitCode));
    RestartRequired := ExitCode = 3010;
    if WizardIsComponentSelected('camera') then InstallNativeComponent('Camera');
    if WizardIsComponentSelected('bridge') then InstallNativeComponent('Bridge');
  end;
end;

function NeedRestart(): Boolean;
begin
  Result := RestartRequired;
end;
