# Add the G3M PRO battery tray to the current user's startup folder.
# Run:  powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $here 'start_tray.vbs'
if (-not (Test-Path $target)) { throw "start_tray.vbs not found: $target" }

$startup = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startup 'G3M PRO Battery.lnk'

$sh = New-Object -ComObject WScript.Shell
$lnk = $sh.CreateShortcut($lnkPath)
$lnk.TargetPath = "$env:WINDIR\System32\wscript.exe"
$lnk.Arguments = '"' + $target + '"'
$lnk.WorkingDirectory = $here
$lnk.Description = 'G3M PRO battery tray'

$icon = Join-Path $here 'app.ico'
if (Test-Path $icon) { $lnk.IconLocation = $icon }

$lnk.Save()
Write-Host "Added to startup:" -ForegroundColor Green
Write-Host "  $lnkPath"
