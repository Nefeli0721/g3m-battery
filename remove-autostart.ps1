# Remove the G3M PRO battery tray from the current user's startup folder.
# Run:  powershell -ExecutionPolicy Bypass -File .\remove-autostart.ps1
$startup = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startup 'G3M PRO Battery.lnk'

if (Test-Path $lnkPath) {
    Remove-Item $lnkPath -Force
    Write-Host "Removed from startup: $lnkPath" -ForegroundColor Green
} else {
    Write-Host "Nothing to remove (startup entry not found)."
}
