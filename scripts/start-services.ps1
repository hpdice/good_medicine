# Runs at logon via Task Scheduler after a PC reboot.
# Brings up docker compose (postgres+backend+ollama), then Cloudflare Tunnel.

$ErrorActionPreference = "Stop"
$projectDir = "C:\Dev\drugTest"

# Start Docker Desktop if it isn't running yet, and wait for the daemon.
if (-not (Get-Process "Docker Desktop" -ErrorAction SilentlyContinue)) {
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    Start-Sleep -Seconds 30
}
$maxWait = 120
$waited = 0
while ($waited -lt $maxWait) {
    docker info > $null 2>&1
    if ($?) { break }
    Start-Sleep -Seconds 5
    $waited += 5
}

Set-Location $projectDir
docker compose up -d

# 외부 노출은 Cloudflare Tunnel이 아니라 C:\Dev\Health 프로젝트가 관리하는
# DuckDNS+Caddy(goodmedicine.duckdns.org)로 처리한다. caddy/duckdns/health-api는
# 전부 restart: always라 Docker 데몬이 뜨면 알아서 같이 복구되므로 여기서 별도로
# 건드릴 필요 없음 (drugtest backend는 8001, health-api는 8000이라 더 이상
# 포트 충돌도 없음 — 2026-08-31 이전엔 여기서 health-api를 강제로 내렸었는데,
# 지금은 그게 오히려 Health 프로젝트를 매 재부팅마다 죽이는 부작용이라 제거함).
