$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $PSScriptRoot "change2pro_relay.py"
$logDir = Join-Path $root ".runtime"
$logPath = Join-Path $logDir "change2pro-relay.log"
$outPath = Join-Path $logDir "change2pro-relay.stdout.log"
$errPath = Join-Path $logDir "change2pro-relay.stderr.log"

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$existing = Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like "*change2pro_relay.py*" } |
  Select-Object -First 1

if ($existing) {
  Write-Output "ALREADY_RUNNING PID=$($existing.ProcessId)"
  Write-Output "LOG=$logPath"
  exit 0
}

$args = @(
  $scriptPath,
  "--host", "127.0.0.1",
  "--port", "5099",
  "--log-file", $logPath
)

$proc = Start-Process -FilePath python `
  -ArgumentList $args `
  -RedirectStandardOutput $outPath `
  -RedirectStandardError $errPath `
  -WindowStyle Hidden `
  -PassThru

Write-Output "STARTED PID=$($proc.Id)"
Write-Output "HEALTH=http://127.0.0.1:5099/health"
Write-Output "LOG=$logPath"
