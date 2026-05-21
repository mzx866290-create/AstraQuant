param(
  [int]$DockerWaitSeconds = 180
)

$ErrorActionPreference = "Continue"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "autostart_docker_stack.log"

function Write-Log {
  param([string]$Message)
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
  Add-Content -Path $LogFile -Value $line
  Write-Host $line
}

Set-Location $Root
Write-Log "Stock platform Docker autostart begin. Root=$Root"

$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
  Write-Log "ERROR docker executable not found."
  exit 1
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
  $dockerDesktopCandidates = @(
    "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
    "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe"
  )
  foreach ($candidate in $dockerDesktopCandidates) {
    if ($candidate -and (Test-Path $candidate)) {
      Write-Log "Docker engine is not ready; starting Docker Desktop."
      Start-Process -FilePath $candidate -WindowStyle Hidden
      break
    }
  }
}

$deadline = (Get-Date).AddSeconds($DockerWaitSeconds)
do {
  docker info *> $null
  if ($LASTEXITCODE -eq 0) {
    Write-Log "Docker engine is ready."
    break
  }
  Write-Log "Docker engine not ready, waiting..."
  Start-Sleep -Seconds 5
} while ((Get-Date) -lt $deadline)

docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Log "ERROR Docker engine did not become ready."
  exit 1
}

Write-Log "Starting docker compose stack without rebuild."
docker compose up -d --no-build *>> $LogFile
if ($LASTEXITCODE -ne 0) {
  Write-Log "ERROR docker compose up failed with exit code $LASTEXITCODE."
  exit $LASTEXITCODE
}

Write-Log "Docker compose ps:"
docker compose ps *>> $LogFile

$healthUrls = @(
  "http://localhost:8001/health",
  "http://localhost:8002/health",
  "http://localhost:8003/health",
  "http://localhost:5175/"
)

foreach ($url in $healthUrls) {
  $ok = $false
  for ($i = 0; $i -lt 36; $i++) {
    try {
      $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
        $ok = $true
        break
      }
    } catch {
      Start-Sleep -Seconds 5
    }
  }
  if ($ok) {
    Write-Log "OK $url"
  } else {
    Write-Log "WARN health check did not pass: $url"
  }
}

Write-Log "Stock platform Docker autostart finished."
