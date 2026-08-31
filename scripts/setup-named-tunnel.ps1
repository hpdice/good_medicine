# NOTE (2026-08-31): not the path actually used — 최종적으로는 도메인 구매 없이
# DuckDNS+Caddy(goodmedicine.duckdns.org, C:\Dev\Health 저장소가 관리)로 갔음.
# 이 스크립트는 나중에 자체 도메인을 쓰기로 하면 그때 참고용으로 남겨둠.
#
# Run this AFTER:
#   1) the domain is added to Cloudflare (or registered there directly)
#   2) `cloudflared tunnel login` has been run once in a browser and picked that domain's zone
#
# Usage: .\setup-named-tunnel.ps1 -Domain "example.com" [-Subdomain "api"] [-TunnelName "good-medicine"]

param(
    [Parameter(Mandatory=$true)][string]$Domain,
    [string]$Subdomain = "api",
    [string]$TunnelName = "good-medicine"
)

$ErrorActionPreference = "Stop"
$hostname = "$Subdomain.$Domain"

Write-Host "Creating tunnel '$TunnelName'..."
cloudflared tunnel create $TunnelName

$tunnelInfo = cloudflared tunnel list --output json | ConvertFrom-Json
$tunnel = $tunnelInfo | Where-Object { $_.name -eq $TunnelName }
$tunnelId = $tunnel.id

Write-Host "Tunnel ID: $tunnelId"

Write-Host "Routing DNS $hostname -> tunnel..."
cloudflared tunnel route dns $TunnelName $hostname

$credFile = "$env:USERPROFILE\.cloudflared\$tunnelId.json"
$configContent = @"
tunnel: $tunnelId
credentials-file: $credFile

ingress:
  - hostname: $hostname
    service: http://localhost:8000
  - service: http_status:404
"@
Set-Content -Path "$env:USERPROFILE\.cloudflared\config.yml" -Value $configContent -Encoding UTF8

Write-Host ""
Write-Host "Done. Backend will be reachable at: https://$hostname"
Write-Host "Test it: cloudflared tunnel run $TunnelName"
