$ErrorActionPreference = 'Stop'
$colorproRoot = Split-Path -Parent $PSScriptRoot
$colorproPython = Join-Path $colorproRoot '.venv\Scripts\pythonw.exe'
$colorproEntry = Join-Path $colorproRoot 'ColorPro.pyw'
$colorproConfig = Get-Content -Raw -LiteralPath (Join-Path $colorproRoot 'configs\local.colorpro.json') | ConvertFrom-Json
$colorproIcon = Join-Path $colorproConfig.state_root 'qa\ui-final\colorpro.ico'
$colorproDesktop = [Environment]::GetFolderPath('Desktop')
$colorproLink = Join-Path $colorproDesktop 'ColorPro.lnk'
if (-not (Test-Path -LiteralPath $colorproPython)) { throw 'Python runtime missing' }
if (-not (Test-Path -LiteralPath $colorproEntry)) { throw 'ColorPro entrypoint missing' }
if (-not (Test-Path -LiteralPath $colorproIcon)) { throw 'ColorPro icon missing' }
$colorproShell = New-Object -ComObject WScript.Shell
if (Test-Path -LiteralPath $colorproLink) {
    $colorproExisting = $colorproShell.CreateShortcut($colorproLink)
    if ($colorproExisting.TargetPath -ne $colorproPython -or $colorproExisting.Arguments -ne ('"' + $colorproEntry + '"')) {
        throw 'A different ColorPro shortcut exists; refusing to overwrite it'
    }
}
$colorproShortcut = $colorproShell.CreateShortcut($colorproLink)
$colorproShortcut.TargetPath = $colorproPython
$colorproShortcut.Arguments = '"' + $colorproEntry + '"'
$colorproShortcut.WorkingDirectory = $colorproRoot
$colorproShortcut.IconLocation = $colorproIcon
$colorproShortcut.Description = 'ColorPro - V39 local photo color correction'
$colorproShortcut.WindowStyle = 1
$colorproShortcut.Save()
Write-Output $colorproLink
