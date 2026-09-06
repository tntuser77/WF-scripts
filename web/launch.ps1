$ErrorActionPreference = "SilentlyContinue"
$venvPy = "C:\Users\Elijah\Documents\wfm\.venv\Scripts\pythonw.exe"
$app = "C:\Users\Elijah\Documents\wfm\web\app.py"
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
if (-not (Port-Open $port)) {
  $ownServer = $true
  Start-Process -FilePath $venvPy -ArgumentList "`"$app`" --exit-when-idle 60"
  for ($i = 0; $i -lt 60 -and -not (Port-Open $port); $i++) { Start-Sleep -Seconds 1 }
}

$win = Start-Process -FilePath $chrome -ArgumentList "--app=http://127.0.0.1:$port/", "--user-data-dir=`"$profile`"" -PassThru

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
