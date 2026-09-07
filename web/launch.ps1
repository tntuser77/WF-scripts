$ErrorActionPreference = "SilentlyContinue"
$webDir = $PSScriptRoot
$repoRoot = Split-Path $webDir
$venvPy = Join-Path $repoRoot ".venv\Scripts\pythonw.exe"
$app = Join-Path $webDir "app.py"
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$profile = "$env:LOCALAPPDATA\WFM-Relic-Tools\ChromeProfile"
$port = 5000

function Port-Open($p) {
  $c = New-Object Net.Sockets.TcpClient
  try { $c.Connect("127.0.0.1", $p); $c.Close(); return $true } catch { return $false }
}

function AppWindows() {
  return Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object { $_.CommandLine -like "*WFM-Relic-Tools*" }
}

function AppServer() {
  return Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like "*wfm*web*app.py*" }
}

$ownServer = $false
$serverReady = Port-Open $port

# Start the window first. Chrome's own startup is the slowest part of a
# cold launch, so get it painting while the server boots in parallel.
# If the server is already warm, go straight to the app. Otherwise show
# a local splash page that flips to the app as soon as the server
# answers, so a cold start never looks dead.
if ($serverReady) {
  $startUrl = "http://127.0.0.1:$port/"
} else {
  $splashPath = Join-Path (Split-Path $app) "static\loading.html"
  $startUrl = "file:///" + ($splashPath -replace "\\", "/")
}

$win = Start-Process -FilePath $chrome -ArgumentList "--app=$startUrl", "--user-data-dir=`"$profile`"", "--no-first-run", "--no-default-browser-check" -PassThru

if (-not $serverReady) {
  $ownServer = $true
  Start-Process -FilePath $venvPy -ArgumentList "`"$app`" --exit-when-idle 180"
}

# Wait until the window closes (X button) or the server goes away (Quit button).
while (-not $win.HasExited) {
  Start-Sleep -Seconds 2
  if ($ownServer -and -not (Port-Open $port)) { break }
}

# Close any leftover app windows (Quit path: server is already gone).
AppWindows | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# No UI left to look at: make sure our server is gone too.
if ($ownServer -and -not (AppWindows)) {
  AppServer | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}
