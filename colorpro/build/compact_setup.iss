{ Shared maintenance checks. Offline installers carry ALL files; compact
  updaters carry ONLY changed files. Neither downloads or runs another setup. }
var
  VerifyPage: TOutputProgressWizardPage;
  MissingComponent: String;

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
var Rows: TStringList; I: Integer;
#ifdef CompactRoot
  Sep: Integer; Name, Hash: String;
#endif
begin
  Result := False;
  Rows := TStringList.Create;
  VerifyPage.Show;
  try
    ExtractTemporaryFile('targets.txt');
    Rows.LoadFromFile(ExpandConstant('{tmp}\targets.txt'));
    for I := 0 to Rows.Count - 1 do
      if not SafePath(ExpandConstant('{app}\') + Rows[I]) then
        RaiseException('Недопустимая ссылка в папке установки.');
#ifdef CompactRoot
    ExtractTemporaryFile('required.txt');
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
#endif
    Result := True;
  finally
    Rows.Free;
    VerifyPage.Hide;
  end;
end;

procedure InitializeWizard;
begin
  VerifyPage := CreateOutputProgressPage('Подготовка ColorPro', 'Проверяем файлы перед установкой.');
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
var InstalledVersion: String;
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
    if not VerifyComponents then
      RaiseException('Этот файл — только обновление. Компонент отсутствует или изменён: ' + MissingComponent + #13#10 +
        'Файлы приложения не изменены. Для первой установки или восстановления скачайте полный установщик с окончанием -Offline.exe со страницы github.com/babkanomer13-dotcom/colorcorrection/releases/latest.');
#ifdef CompactRoot
    Log('COMPACT_UPDATE: runtime verified; no component download.');
#else
    Log('OFFLINE_INSTALL: all components embedded; identical files are preserved.');
#endif
  except
    Result := GetExceptionMessage;
  end;
end;
