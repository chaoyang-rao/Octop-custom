$ErrorActionPreference = 'Stop'
$build = Join-Path $PSScriptRoot '..\..\build\windows'
$installer = Join-Path $build 'Dora-Windows-x64-0.8.0-Setup.exe'
$process = Start-Process -FilePath (Resolve-Path $installer) -ArgumentList '/S' -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Installer failed: $($process.ExitCode)" }
$exe = Join-Path $env:LOCALAPPDATA 'Programs\OctopCompanion\Dora.exe'
if (!(Test-Path $exe)) { throw 'Dora executable not installed' }
$home = Join-Path $env:LOCALAPPDATA 'OctopCompanion'
$app = Start-Process -FilePath $exe -PassThru
try {
  $health = $null
  for ($i=0; $i -lt 240; $i++) {
    Start-Sleep -Milliseconds 500
    if ($app.HasExited) { throw 'Installed Dora exited before readiness' }
    try {
      $port = [int](Get-Content (Join-Path $home 'port') -Raw)
      $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health/companion" -TimeoutSec 1
      if ($health.companion -and $health.instance) { break }
    } catch { }
  }
  if (!$health.companion) { throw 'Installed engine did not become ready' }
  $app.Refresh()
  if (!$app.MainWindowHandle) { throw 'Installed app has no visible chat window' }
  $sentinel = Join-Path $home 'Data\uninstall-preserves-data.txt'
  Set-Content $sentinel 'isolated Windows installer preservation test'
  # Only the acceptance process created above is ended. Its own engine observes stdin EOF.
  Stop-Process -Id $app.Id -Force
  Start-Sleep -Seconds 2
  $uninstall = Join-Path (Split-Path $exe) 'Uninstall.exe'
  $uninstaller = Start-Process -FilePath $uninstall -ArgumentList '/S' -Wait -PassThru
  if ($uninstaller.ExitCode -ne 0) { throw 'Silent uninstall failed' }
  if (!(Test-Path $sentinel)) { throw 'Uninstall removed member data' }
  @{ installed = $true; independent_engine = $true; native_chat_window = $true; uninstall_preserved_data = $true; real_employee_sso_tested = $false } | ConvertTo-Json | Set-Content (Join-Path $build '..\windows-installer-check.json')
} finally {
  if (!$app.HasExited) { Stop-Process -Id $app.Id -Force }
}
