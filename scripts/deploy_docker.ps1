param(
  [string[]]$Services = @("analysis-service", "data-crawler", "user-service"),
  [switch]$SkipWeb
)

$ErrorActionPreference = "Stop"
$env:DOCKER_BUILDKIT = "0"

Write-Host "[deploy] building backend services: $($Services -join ', ')"
docker compose build --pull=false @Services
docker compose up -d @Services

if (-not $SkipWeb) {
  Write-Host "[deploy] building frontend dist"
  npm --prefix frontend/web run build

  Write-Host "[deploy] updating web container from local dist"
  docker cp frontend/web/dist/. stock_platform_web:/usr/share/nginx/html
  docker cp frontend/web/nginx.conf stock_platform_web:/etc/nginx/nginx.conf
  docker exec stock_platform_web nginx -s reload
  docker commit stock_platform_web demo4-web:latest | Out-Host
  docker compose up -d --no-build --force-recreate web
}

Write-Host "[deploy] current service status"
docker compose ps web user-service analysis-service data-crawler
