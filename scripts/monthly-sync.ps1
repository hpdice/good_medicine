<#
굿메디슨 공공데이터 월간 갱신 스크립트

왜: 식약처 DUR·허가정보는 계속 바뀐다.
    금기 규칙이 오래되면 새로 지정된 병용금기를 못 잡으므로 매월 자동으로 갱신한다.

무엇을 하나 (한 단계라도 실패하면 거기서 멈추고 종료 코드 1):
  0. 백엔드 헬스체크 (/health 가 DB 까지 확인)
  1. 백업 (scripts/backup-db.ps1 -Verify — 복원 검증 포함). 실패하면 갱신 자체를 하지 않는다.
  2. 동기화: overview → approval → dur_contraindications → efcy_dplct → dur_age_caution →
     dur_pregnancy → dur_extra_codes → build_drug_ingredients
     - dur_contraindications 가 일일 할당량 등으로 중단되면(체크포인트가 남음) QuotaWaitMinutes 뒤
       체크포인트부터 다시 시도, 최대 QuotaRetries 번.
  3. extract_risk_tags — 새/바뀐 금기 문장의 위험 태그(로컬 LLM). 실패해도 판정과 무관해 경고만.
  4. validate_db.py — 품질 게이트(치명적 문제가 있으면 실패).

실행:
  powershell -ExecutionPolicy Bypass -File C:\Dev\drugTest\scripts\monthly-sync.ps1
  powershell -ExecutionPolicy Bypass -File C:\Dev\drugTest\scripts\monthly-sync.ps1 -Only dur_age_caution   (일부만)
  # 병용금기 전체 재수집처럼 할당량을 여러 번 넘길 긴 작업 (쉼표로 여러 단계, 재시도 횟수 늘림):
  powershell -ExecutionPolicy Bypass -File C:\Dev\drugTest\scripts\monthly-sync.ps1 -Only dur_contraindications,build_drug_ingredients -QuotaRetries 24
  (중간에 강제로 멈추려면 scripts\stop-dur-ingr-sync.ps1 — 체크포인트는 남아 다음 실행이 이어받는다)
  매월 자동 실행 등록은 docs/operations.md 참고. 로그: D:\drugTest\sync-logs\
#>
param(
    [string]$LogDir = "D:\drugTest\sync-logs",
    [int]$QuotaRetries = 3,
    [int]$QuotaWaitMinutes = 60,
    [string[]]$Only
)

$ErrorActionPreference = "Continue"
# docker exec 의 UTF-8 출력을 한글 그대로 받기 위해 (PowerShell 5.1 기본은 CP949)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$container = "drugtest-backend-1"
$checkpoint = "/var/lib/goodmedicine/dur_contraindications_checkpoint.txt"
$steps = @("overview", "approval", "dur_contraindications", "efcy_dplct",
           "dur_age_caution", "dur_pregnancy", "dur_extra_codes", "build_drug_ingredients")
# -File 로 실행하면 "-Only a,b" 가 배열이 아니라 문자열 하나로 넘어오므로 쉼표로 직접 나눈다.
if ($Only) { $steps = @($Only | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$logFile = Join-Path $LogDir ("sync-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")

function Log([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Write-Output $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

# 컨테이너에서 python 스크립트를 돌리고 출력(진행 막대 줄은 제외)을 로그에 남긴 뒤 종료 코드를 돌려준다.
function RunInBackend([string[]]$argv) {
    $out = docker exec -w /app $container python @argv 2>&1
    $code = $LASTEXITCODE
    foreach ($l in ($out -split "`r|`n")) {
        if ($l.Trim() -and $l -notmatch '^\s*페이지\s') { Add-Content -Path $logFile -Value "    $l" -Encoding UTF8 }
    }
    return $code
}

function Fail([string]$msg) { Log "실패: $msg"; exit 1 }

Log "===== 월간 갱신 시작 (단계: $($steps -join ', ')) ====="

# 0. 헬스체크
try { $status = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8001/health" -TimeoutSec 10).StatusCode }
catch { $status = 0 }
if ($status -ne 200) { Fail "백엔드 헬스체크 실패(HTTP $status) — docker compose 상태 확인" }

# 1. 백업
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "backup-db.ps1") -Verify | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "백업 실패 — 갱신을 진행하지 않음 (D:\drugTest\backups\backup.log)" }
Log "백업 완료(복원 검증 포함)"

# 2. 동기화
foreach ($step in $steps) {
    $attempt = 0
    while ($true) {
        $attempt++
        Log "[$step] 시작 (시도 $attempt)"
        $code = RunInBackend @("sync.py", $step)
        if ($code -eq 0) { Log "[$step] 완료"; break }

        $hasCheckpoint = (docker exec $container sh -c "test -f $checkpoint && echo yes") -eq "yes"
        if ($step -eq "dur_contraindications" -and $hasCheckpoint -and $attempt -le $QuotaRetries) {
            Log "[$step] 중단 — 체크포인트 있음(할당량 초과 추정). $QuotaWaitMinutes 분 뒤 이어서 재시도"
            Start-Sleep -Seconds ($QuotaWaitMinutes * 60)
            continue
        }
        Fail "[$step] 종료 코드 $code — 이후 단계 중단 (상세는 이 로그)"
    }
}

# 3. 위험 태그 (판정 무관 — 실패해도 경고만)
$code = RunInBackend @("sync.py", "extract_risk_tags")
if ($code -eq 0) { Log "extract_risk_tags 완료" } else { Log "경고: extract_risk_tags 실패(종료 코드 $code) — 표시용 태그만 영향" }

# 4. 품질 게이트
$code = RunInBackend @("validate_db.py")
if ($code -ne 0) { Fail "품질 게이트 실패 — 필요하면 직전 백업으로 복원 (docs/operations.md 2절)" }
Log "품질 게이트 통과"

# 로그는 최근 24개만 보관
Get-ChildItem -Path $LogDir -Filter "sync-*.log" | Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 24 | Remove-Item

Log "===== 월간 갱신 완료 ====="
exit 0
