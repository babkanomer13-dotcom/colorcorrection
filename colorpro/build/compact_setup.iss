{ Included by setup.iss only for compact, self-contained maintenance installers.
  Omitted components are hashed before writing; clean installs fetch a pinned
  complete baseline automatically. An in-app update NEVER silently downloads it. }
var
  ComponentPage: TDownloadWizardPage;
  VerifyPage: TOutputProgressWizardPage;
  MissingComponent: String;
  ComponentNames, ComponentHashes: TStringList;

function GetFileAttributesW(Name: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function SafePath(Name: String): Boolean;
var Attr: LongWord; Parent: String;
begin
  Result := False;
  while Length(Name) > 3 do begin
    Attr := GetFileAttributesW(Name);
    if (Attr <> $FFFFFFFF) and ((Attr and $400) <> 0) then Exit;
    Parent := ExtractFileDir(Name);
    if Parent = Name then Exit;
    Name := Parent;
  end;
  Result := True;
end;

function MatchesFile(Name, Hash: String): Boolean;
begin
  Result := False;
  if not SafePath(Name) then RaiseException('Недопустимая ссылка в папке установки.');
  if FileExists(Name) then Result := CompareText(GetSHA256OfFile(Name), Hash) = 0;
end;

function NeedsFile(Name, Hash: String): Boolean;
begin
  Result := not MatchesFile(ExpandConstant('{app}\') + Name, Hash);
end;

function VerifyComponents: Boolean;
var Rows: TStringList; I, Sep: Integer; Name, Hash: String;
begin
  Result := False;
  Rows := TStringList.Create;
  VerifyPage.Show;
  try
    ExtractTemporaryFile('required.txt');
    ExtractTemporaryFile('targets.txt');
    Rows.LoadFromFile(ExpandConstant('{tmp}\targets.txt'));
    for I := 0 to Rows.Count - 1 do
      if not SafePath(ExpandConstant('{app}\') + Rows[I]) then
        RaiseException('Недопустимая ссылка в папке установки.');
    Rows.LoadFromFile(ExpandConstant('{tmp}\required.txt'));
    for I := 0 to Rows.Count - 1 do begin
      Sep := Pos('|', Rows[I]);
      Hash := Copy(Rows[I], 1, Sep - 1);
      Name := Copy(Rows[I], Sep + 1, MaxInt);
      VerifyPage.SetText('Проверяем установленные компоненты', Name);
      VerifyPage.SetProgress(I, Rows.Count);
      if not MatchesFile(ExpandConstant('{app}\') + Name, Hash) then begin
        MissingComponent := Name;
        Log('Missing or changed runtime: ' + Name);
        Exit;
      end;
    end;
    Result := True;
  finally
    Rows.Free;
    VerifyPage.Hide;
  end;
end;

procedure AddComponent(Name, Hash, Url: String);
var Cached: String;
begin
  ComponentNames.Add(Name);
  ComponentHashes.Add(Hash);
  { Optional already-downloaded files; their hashes are always verified. }
  Cached := ExpandConstant('{param:COMPONENTSROOT|{src}}') + '\' + Name;
  if MatchesFile(Cached, Hash) then begin
    if not CopyFile(Cached, ExpandConstant('{tmp}\') + Name, False) then
      RaiseException('Не удалось подготовить компонент: ' + Name);
  end else
    ComponentPage.Add(Url, Name, Hash);
end;

#include CompactRoot + "\baseline.iss"

procedure InitializeWizard;
begin
  ComponentPage := CreateDownloadPage('Компоненты ColorPro',
    'Первая установка: загружаем библиотеки и модель. При обычном обновлении они не нужны.', nil);
  ComponentPage.ShowBaseNameInsteadOfUrl := True;
  VerifyPage := CreateOutputProgressPage('Подготовка ColorPro', 'Проверяем файлы перед установкой.');
  ComponentNames := TStringList.Create;
  ComponentHashes := TStringList.Create;
end;

function VersionPart(var Value: String): Integer;
var Sep: Integer; Part: String;
begin
  Sep := Pos('.', Value);
  if Sep = 0 then Sep := Length(Value) + 1;
  Part := Copy(Value, 1, Sep - 1);
  Delete(Value, 1, Sep);
  Result := StrToIntDef(Part, -1);
  if Result < 0 then RaiseException('Некорректная версия установленного ColorPro.');
end;

function IsNewer(Installed, Incoming: String): Boolean;
var I, A, B: Integer;
begin
  Result := False;
  for I := 1 to 3 do begin
    A := VersionPart(Installed);
    B := VersionPart(Incoming);
    if A > B then begin Result := True; Exit; end;
    if A < B then Exit;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var ExitCode, I: Integer; Params, InstalledVersion: String;
begin
  Result := '';
  try
    if not SafePath(ExpandConstant('{app}')) then
      RaiseException('Папка установки не должна быть ссылкой.');
    if CheckForMutexes('{#ProductMutex}') then
      RaiseException('Закройте ColorPro перед установкой. Обработка не будет прервана.');
    if RegQueryStringValue(HKCU64,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#ProductId}_is1',
      'DisplayVersion', InstalledVersion) then
      if IsNewer(InstalledVersion, '{#ProductVersion}') then
        RaiseException('Установлена более новая версия ColorPro. Откат отменён.');
    if VerifyComponents then begin
      Log('COMPACT_UPDATE: runtime verified; no component download.');
      Exit;
    end;
    if ExpandConstant('{param:COLORPROUPDATE|0}') = '1' then
      RaiseException('Компонент отсутствует или изменён: ' + MissingComponent + #13#10 +
        'Обновление остановлено без изменения файлов. Запустите этот установщик вручную для восстановления компонентов.');
    if FileExists(ExpandConstant('{app}\ColorPro.exe')) then
      if SuppressibleMsgBox('Для восстановления компонентов требуется загрузить полный комплект. Продолжить?',
           mbConfirmation, MB_YESNO, IDNO) <> IDYES then
        RaiseException('Восстановление отменено.');
    ComponentNames.Clear;
    ComponentHashes.Clear;
    ComponentPage.Clear;
    AddBaselineFiles;
    ComponentPage.Show;
    try
      ComponentPage.Download;
    finally
      ComponentPage.Hide;
    end;
    for I := 0 to ComponentNames.Count - 1 do
      if not MatchesFile(ExpandConstant('{tmp}\') + ComponentNames[I], ComponentHashes[I]) then
        RaiseException('Контрольная сумма компонента не совпала.');
    Params := '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOICONS /TASKS="" /DIR="' + ExpandConstant('{app}') +
      '" /LOG="' + ExpandConstant('{localappdata}\{#FolderName}\components-install.log') + '"';
    ForceDirectories(ExpandConstant('{localappdata}\{#FolderName}'));
    VerifyPage.Show;
    try
      VerifyPage.SetText('Устанавливаем компоненты ColorPro', 'Это требуется только при первой установке или восстановлении.');
      if not Exec(ExpandConstant('{tmp}\') + BaselineInstaller, Params, '', SW_HIDE,
                  ewWaitUntilTerminated, ExitCode) then RaiseException('Не удалось установить компоненты.');
      if ExitCode <> 0 then RaiseException('Установка компонентов завершилась с кодом ' + IntToStr(ExitCode));
    finally
      VerifyPage.Hide;
    end;
    if not VerifyComponents then RaiseException('Не удалось проверить компонент: ' + MissingComponent);
    Log('FRESH_INSTALL: baseline installed and verified.');
  except
    Result := GetExceptionMessage;
  end;
end;

procedure DeinitializeSetup;
begin
  if ComponentNames <> nil then ComponentNames.Free;
  if ComponentHashes <> nil then ComponentHashes.Free;
end;
