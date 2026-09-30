$ErrorActionPreference = 'Stop'
$colorproPython = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
$colorproLauncher = Join-Path $PSScriptRoot 'ColorPro.pyw'
if (-not (Test-Path -LiteralPath $colorproPython)) { throw 'ColorPro runtime not found.' }
Start-Process -FilePath $colorproPython -ArgumentList ('"' + $colorproLauncher + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
