<#
컨테이너에서 돌고 있는 DUR 병용금기 성분 sync(python sync.py dur_contraindications)를
모두 종료한다. 창을 닫아서 잔여(orphan) 프로세스가 남았을 때 사용.
체크포인트 파일은 그대로 두므로 다음 실행 때 이어진다.

실행:
  powershell -ExecutionPolicy Bypass -File C:\Dev\drugTest\scripts\stop-dur-ingr-sync.ps1
#>
$container = "drugtest-backend-1"

# sh 스크립트를 stdin으로 넘긴다 (인용부호 깨짐 회피)
$script = @'
k=0
for d in /proc/[0-9]*; do
  [ "$(cat $d/comm 2>/dev/null)" = python ] || continue
  tr "\0" " " < $d/cmdline 2>/dev/null | grep -q dur_contraindications || continue
  kill "$(basename $d)" && k=$((k+1))
done
echo "종료: ${k}개"
echo "checkpoint: $(cat /var/lib/goodmedicine/dur_contraindications_checkpoint.txt 2>/dev/null)"
'@

$script | docker exec -i $container sh
