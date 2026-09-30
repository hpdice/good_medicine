<#
굿메디슨 DB 백업 스크립트

무엇을 하나:
  1. drugtest-postgres-1 컨테이너 안에서 pg_dump(custom 포맷, 압축)로 덤프를 만든다.
  2. docker cp 로 호스트 백업 폴더에 꺼낸다(PowerShell 5.1 의 '>' 리다이렉트는 바이너리를 깨뜨림).
  3. -Verify 를 주면 임시 DB(drugtest_restore_check)에 실제로 복원해 보고, 핵심 테이블 행 수가
     운영 DB와 같은지 비교한 뒤 임시 DB를 지운다. "백업이 있다"가 아니라 "복원된다"를 확인.
  4. KeepDays 보다 오래된 덤프를 지운다.

암호화 키는 여기서 백업하지 않는다(일부러):
  덤프 안의 건강·복약 정보는 FIELD_ENCRYPTION_KEY 로 암호화돼 있다. 키를 덤프 옆에 두면
  덤프가 유출될 때 키까지 같이 유출돼 암호화가 무의미해진다. 키(.env 의 FIELD_ENCRYPTION_KEY,
  SECRET_KEY)는 비밀번호 관리자나 오프라인 매체에 **따로** 보관할 것 — 키를 잃으면 이 덤프의
  암호화 필드는 영영 복구할 수 없다. 절차: docs/operations.md

실행:
  powershell -ExecutionPolicy Bypass -File C:\Dev\drugTest\scripts\backup-db.ps1 -Verify
  (매일 자동 실행 등록은 docs/operations.md 참고)
#>
param(
    [string]$BackupDir = "D:\drugTest\backups",
    [int]$KeepDays = 14,
    [switch]$Verify
)

$ErrorActionPreference = "Continue"
$container = "drugtest-postgres-1"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$name = "drugtest-$stamp.dump"
$containerPath = "/tmp/$name"

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$logFile = Join-Path $BackupDir "backup.log"

function Log([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Write-Output $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

# 컨테이너 안 sh 로 넘길 명령. 작은따옴표 문자열이라 $POSTGRES_USER 등은 컨테이너 안에서 풀린다.
# (값에 공백이 없어 큰따옴표가 필요 없다 — PowerShell 5.1 의 네이티브 인자 따옴표 깨짐 회피)
function InContainer([string]$cmd) {
    docker exec $container sh -c $cmd
    return $LASTEXITCODE
}

$ok = $false
try {
    if ((InContainer 'pg_isready -q') -ne 0) { throw "PostgreSQL 컨테이너가 응답하지 않음 (docker compose up -d postgres)" }

    if ((InContainer ('pg_dump -Fc -U $POSTGRES_USER -d $POSTGRES_DB -f ' + $containerPath)) -ne 0) {
        throw "pg_dump 실패"
    }

    $dest = Join-Path $BackupDir $name
    docker cp "${container}:$containerPath" $dest
    if ($LASTEXITCODE -ne 0) { throw "docker cp 실패" }
    $sizeMb = [math]::Round((Get-Item $dest).Length / 1MB, 1)
    if ($sizeMb -lt 0.1) { throw "덤프가 비정상적으로 작음: $sizeMb MB" }
    Log "덤프 완료: $dest ($sizeMb MB)"

    if ($Verify) {
        $tables = "drugs drug_ingredients dur_ingredient_contraindications users medicine_box_entries"
        $restore = 'dropdb --if-exists -U $POSTGRES_USER drugtest_restore_check && ' +
                   'createdb -U $POSTGRES_USER drugtest_restore_check && ' +
                   'pg_restore -U $POSTGRES_USER -d drugtest_restore_check --no-owner ' + $containerPath
        if ((InContainer $restore) -ne 0) { throw "복원 검증 실패: pg_restore 오류" }

        $mismatch = @()
        foreach ($t in $tables.Split(" ")) {
            $q = "select count(*) from $t"
            $live = docker exec $container sh -c ('psql -At -U $POSTGRES_USER -d $POSTGRES_DB -c ' + "'$q'")
            $rest = docker exec $container sh -c ('psql -At -U $POSTGRES_USER -d drugtest_restore_check -c ' + "'$q'")
            if ("$live".Trim() -ne "$rest".Trim()) { $mismatch += "$t(운영 $live / 복원 $rest)" }
        }
        InContainer 'dropdb --if-exists -U $POSTGRES_USER drugtest_restore_check' | Out-Null
        if ($mismatch.Count -gt 0) { throw "복원 검증 실패: 행 수 불일치 $($mismatch -join ', ')" }
        Log "복원 검증 통과: $tables 행 수 일치"
    }

    $old = Get-ChildItem -Path $BackupDir -Filter "drugtest-*.dump" |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) }
    foreach ($f in $old) { Remove-Item $f.FullName; Log "보관기간($KeepDays 일) 지난 덤프 삭제: $($f.Name)" }

    $ok = $true
}
catch {
    Log "실패: $_"
}
finally {
    InContainer ('rm -f ' + $containerPath) | Out-Null
}

if (-not $ok) { exit 1 }
