<#
DUR 병용금기 성분(ingredient) sync 자동 완주 스크립트

무엇을 하나:
  docker exec drugtest-backend-1 python sync.py dur_contraindications 를 반복 실행한다.
  - 공공데이터 일일 할당량에 막혀 중단되면(체크포인트 파일이 남음) 1시간 뒤 재시도,
    체크포인트에서 이어서 진행한다.
  - sweep이 797,458행을 완주하면 체크포인트 파일이 사라진다 -> build_drug_ingredients
    한 번 돌리고 스크립트 종료.

실행:
  powershell -ExecutionPolicy Bypass -File C:\Dev\drugTest\run-dur-ingr-sync.ps1

  이 창은 열어둬야 한다(Claude Code와 무관, 이 PowerShell 창에만 종속).
  컴퓨터 절전/종료 시 멈춤 -> 전원 옵션에서 절전 끄기 권장. 멈춰도 체크포인트는
  파일에 남아 다음 실행 때 이어짐(데이터 손실 없음).
#>

$ErrorActionPreference = "Continue"
$container = "drugtest-backend-1"
$retryDelaySeconds = 3600   # 할당량 초과 시 재시도 간격 (1시간)

function Now { (Get-Date -Format "MM-dd HH:mm:ss") }

# sh 스크립트를 인자 대신 stdin으로 넘긴다 (PowerShell -> 네이티브 exe 인용부호 깨짐 회피)
function Invoke-InContainer([string]$shScript) {
    return ($shScript | docker exec -i $container sh 2>$null)
}

function Get-Checkpoint {
    try {
        $v = Invoke-InContainer 'cat /var/lib/goodmedicine/dur_contraindications_checkpoint.txt 2>/dev/null'
        return ($v | Out-String).Trim()
    } catch {
        return "ERR"
    }
}

Write-Host "[$(Now)] DUR 병용금기 성분 sync 자동 실행 시작. 중단하려면 Ctrl+C."

# 중복 실행 방지 — 컨테이너에 이미 python sync가 돌고 있으면 그냥 종료
# (comm=python 인 프로세스만 셈 -> 이 체크 스크립트 자신(sh)은 제외됨)
$dupChk = @'
n=0
for d in /proc/[0-9]*; do
  [ "$(cat $d/comm 2>/dev/null)" = python ] || continue
  tr "\0" " " < $d/cmdline 2>/dev/null | grep -q dur_contraindications && n=$((n+1))
done
echo $n
'@
$already = Invoke-InContainer $dupChk
if (([int]($already | Out-String).Trim()) -gt 0) {
    Write-Host "[$(Now)] 이미 컨테이너에서 sync가 실행 중입니다. 이 창은 종료합니다 (중복 실행 방지)."
    Write-Host "         정말 새로 돌리려면 먼저:  powershell -File C:\Dev\drugTest\stop-dur-ingr-sync.ps1"
    exit 1
}

while ($true) {

    # 컨테이너 살아있는지 확인
    $running = docker ps --filter "name=$container" --filter "status=running" --format "{{.Names}}"
    if ([string]::IsNullOrWhiteSpace($running)) {
        Write-Host "[$(Now)] $container 가 실행 중이 아님. 60초 후 재확인..."
        Start-Sleep -Seconds 60
        continue
    }

    Write-Host "[$(Now)] sync.py dur_contraindications 실행..."
    try {
        docker exec $container python sync.py dur_contraindications
    } catch {
        Write-Host "[$(Now)] docker exec 오류: $_"
    }

    $ckpt = Get-Checkpoint
    Write-Host "[$(Now)] 실행 종료. 체크포인트: '$ckpt'"

    if ($ckpt -eq "ERR") {
        Write-Host "[$(Now)] 체크포인트 확인 실패 — 60초 후 재시도."
        Start-Sleep -Seconds 60
        continue
    }

    if ([string]::IsNullOrWhiteSpace($ckpt)) {
        Write-Host "[$(Now)] 체크포인트 없음 -> sweep 완주. build_drug_ingredients 실행."
        try {
            docker exec $container python sync.py build_drug_ingredients
        } catch {
            Write-Host "[$(Now)] build_drug_ingredients 오류: $_"
        }
        docker exec $container python sync.py status
        Write-Host "[$(Now)] 완료. 스크립트 종료."
        break
    }

    Write-Host "[$(Now)] page $ckpt 에서 중단됨(할당량 추정). $($retryDelaySeconds/60)분 후 재개..."
    Start-Sleep -Seconds $retryDelaySeconds
}
