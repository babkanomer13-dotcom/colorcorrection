#ifndef ProductVersion
  #define ProductVersion "1.3.1"
#endif
#ifdef Legacy
  #define ProductName "ColorPro Win7"
  #define FolderName "ColorProWin7"
  #define OutputName "ColorPro-" + ProductVersion + "-Win7-x64-Setup"
  #define ProductMutex "Local\ColorProWin7.Desktop"
  #define ProductId "{AA28C1D8-D7D9-4980-B74B-6961F8A11742}"
#else
  #define ProductName "ColorPro"
  #define FolderName "ColorPro"
  #define OutputName "ColorPro-" + ProductVersion + "-Win10-x64-Setup"
  #define ProductMutex "Local\ColorPro.Desktop"
  #define ProductId "{71C64124-2B1F-421C-B3E2-D204979CD1E5}"
#endif
#ifdef CompactRoot
  #define PayloadRoot CompactRoot
#else
  #ifndef FullRoot
    #error A verified CompactRoot or FullRoot file plan is required
  #endif
  #define PayloadRoot FullRoot
  #define OutputName StringChange(OutputName, "-Setup", "-Offline")
#endif
[Setup]
AppId={{#ProductId}
AppName={#ProductName}
AppVersion={#ProductVersion}
AppMutex={#ProductMutex}
SetupMutex=Local\{#FolderName}.CompactSetup
AppPublisher=ColorPro
DefaultDirName={localappdata}\Programs\{#FolderName}
DefaultGroupName={#ProductName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#ifdef Legacy
MinVersion=6.1sp1
InfoBeforeFile={#StageRoot}\README-WIN7.txt
#else
MinVersion=10.0
InfoBeforeFile={#StageRoot}\README-SETUP.txt
#endif
OutputDir={#ReleaseRoot}
OutputBaseFilename={#OutputName}
SetupIconFile={#StageRoot}\colorpro.ico
UninstallDisplayIcon={app}\ColorPro.exe
#ifdef CompactRoot
Compression=lzma2/fast
#else
Compression=lzma2/ultra64
#endif
SolidCompression=yes
LZMANumBlockThreads=4
LZMAUseSeparateProcess=yes
WizardStyle=modern
DisableProgramGroupPage=yes
AllowNoIcons=yes
DisableDirPage=no
DisableWelcomePage=no
WizardSizePercent=110
CloseApplications=no
RestartApplications=no
SetupLogging=yes
UninstallDisplayName={#ProductName} {#ProductVersion}
DiskSpanning=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; Flags: unchecked

[Files]
#include PayloadRoot + "\files.iss"
Source: "{#PayloadRoot}\targets.txt"; Flags: dontcopy
#ifdef CompactRoot
Source: "{#CompactRoot}\required.txt"; Flags: dontcopy
#endif

[Icons]
Name: "{group}\{#ProductName}"; Filename: "{app}\ColorPro.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\{#ProductName}"; Filename: "{app}\ColorPro.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\Проверка компонентов"; Filename: "{app}\ColorPro.exe"; Parameters: "--diagnose ""{localappdata}\{#FolderName}\diagnostics.json"" --device cpu"; WorkingDir: "{app}"
Name: "{group}\Удалить {#ProductName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\ColorPro.exe"; Description: "Запустить {#ProductName}"; Flags: nowait postinstall skipifsilent

; Never remove user photographs, settings, logs or processed outputs on uninstall.
[Code]
#include "compact_setup.iss"
#ifdef Legacy
function GetModuleHandle(Name: String): LongWord;
  external 'GetModuleHandleW@kernel32.dll stdcall';
function GetProcAddress(Module: LongWord; Name: AnsiString): LongWord;
  external 'GetProcAddress@kernel32.dll stdcall';
#endif
function InitializeSetup(): Boolean;
var Attempt: Integer;
begin
  { Give the launching ColorPro process time to exit. Other instances are never killed. }
  if ExpandConstant('{param:COLORPROUPDATE|0}') = '1' then
    for Attempt := 1 to 100 do begin
      if not CheckForMutexes('{#ProductMutex}') then Break;
      Sleep(100);
    end;
#ifdef Legacy
  Result := GetProcAddress(GetModuleHandle('kernel32.dll'), 'AddDllDirectory') <> 0;
  if not Result then
    MsgBox('Требуется Windows 7 SP1 x64 с обновлением KB2533623 / KB3063858 либо заменяющим пакетом. Установите обновления Windows и повторите установку.', mbError, MB_OK);
#else
  Result := True;
#endif
end;
