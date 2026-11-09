#!/bin/sh
# 허가정보 상세를 받을 수 있는 만큼 계속 DB에 적재한다(sync.py permit_detail 반복 실행).
# 일일 호출 한도(약 10,000건)나 예약분(--reserve) 때문에 멈추면 15분 쉬었다가 이어 받고, 받을 약이 없으면 끝낸다.
# 컨테이너 안에서 돌기 때문에 컨테이너가 다시 만들어지면 멈춘다 — 같은 명령으로 다시 시작하면 이어 받는다.
#
# BURN_FIRST=1이면 먼저 예약분 없이(--reserve=0) 오늘 남은 호출을 모두 쓴 뒤 반복에 들어간다(일일 한도가 하루 단위로 초기화된다고
# 볼 때 오늘 남은 호출은 내일 못 쓴다 — 초기화 시각은 미확인). 반복 구간은 예약분 1,500을 남겨 앱의 실시간 보충용으로 둔다.
#
# 시작 (저장소 루트에서, 백엔드 컨테이너가 떠 있을 때):
#   docker cp scripts/permit-detail-loop.sh drugtest-backend-1:/tmp/permit-detail-loop.sh
#   docker exec -d drugtest-backend-1 sh /tmp/permit-detail-loop.sh          # 예약분을 남기며 반복
#   docker exec -d -e BURN_FIRST=1 drugtest-backend-1 sh /tmp/permit-detail-loop.sh   # 오늘 남은 호출부터 모두 쓰고 반복
# 진행 확인:
#   docker exec drugtest-backend-1 tail -5 /var/lib/goodmedicine/permit_detail.log
LOG=/var/lib/goodmedicine/permit_detail.log
cd /app
if [ "$BURN_FIRST" = "1" ]; then
  echo "=== $(date '+%F %T') 오늘 남은 호출 모두 사용(--reserve=0) ===" >> $LOG
  PYTHONPATH=/app python -u sync.py permit_detail --limit=100000 --concurrency=8 --reserve=0 >> $LOG 2>&1
fi
while true; do
  echo "=== $(date '+%F %T') 실행 ===" >> $LOG
  PYTHONPATH=/app python -u sync.py permit_detail --limit=100000 --concurrency=8 --reserve=1500 >> $LOG 2>&1
  if tail -n 30 $LOG | grep -q "적재 대상 0건"; then echo "=== $(date '+%F %T') 남은 약 없음 — 종료 ===" >> $LOG; break; fi
  echo "=== $(date '+%F %T') 멈춤 — 15분 뒤 이어서 ===" >> $LOG
  sleep 900
done
