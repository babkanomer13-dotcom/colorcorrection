from pathlib import Path

BUILD = Path(__file__).resolve().parents[1] / "build"


def test_installer_notifies_windows_after_installing_new_icons():
    setup = (BUILD / "setup.iss").read_text("utf8")
    assert "ChangesAssociations=yes" in setup
    assert '#include "shortcuts_setup.iss"' in setup
    code = (BUILD / "shortcuts_setup.iss").read_text("utf8")
    assert "if CurStep <> ssPostInstall then Exit" in code
    assert "NotifyColorProIcon($2000, $3005, Name, 0)" in code
    assert "if FileExists(Name) then begin" in code
    for item in ("{app}\\ColorPro.exe", "{userdesktop}", "{commondesktop}", "{group}"):
        assert item in code


def test_icon_notification_does_not_rewrite_links_or_delete_caches():
    code = (BUILD / "shortcuts_setup.iss").read_text("utf8")
    for forbidden in (
        "DelTree(",
        "DeleteFile(",
        "taskkill",
        "ie4uinit",
        "IconCache.db",
        "CreateOleObject",
        "Link.Save",
        "FindFirst",
    ):
        assert forbidden not in code
