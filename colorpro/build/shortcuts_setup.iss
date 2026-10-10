{ Notify the Windows shell after replacing the executable and shortcut icons.
  ChangesAssociations=yes additionally sends SHCNE_ASSOCCHANGED (as in RetushPro).
  Do not rewrite arbitrary shortcuts, delete icon caches or restart Explorer. }
procedure NotifyColorProIcon(EventId, Flags: LongWord; Item: String; Reserved: Integer);
  external 'SHChangeNotify@shell32.dll stdcall';

procedure RefreshColorProIcon(const Name: String);
begin
  if FileExists(Name) then begin
    { SHCNE_UPDATEITEM, SHCNF_PATHW | SHCNF_FLUSHNOWAIT. }
    NotifyColorProIcon($2000, $3005, Name, 0);
    Log('COLORPRO_ICON_NOTIFY: ' + Name);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then Exit;
  RefreshColorProIcon(ExpandConstant('{app}\ColorPro.exe'));
  RefreshColorProIcon(ExpandConstant('{userdesktop}\{#ProductName}.lnk'));
  RefreshColorProIcon(ExpandConstant('{commondesktop}\{#ProductName}.lnk'));
  RefreshColorProIcon(ExpandConstant('{group}\{#ProductName}.lnk'));
  RefreshColorProIcon(ExpandConstant('{group}\Проверка компонентов.lnk'));
  RefreshColorProIcon(ExpandConstant('{group}\Удалить {#ProductName}.lnk'));
  Log('COLORPRO_ICON_REFRESH_COMPLETE: shell notified; no cache files deleted.');
end;
