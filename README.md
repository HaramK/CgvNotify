# schedule-watcher

특정 극장의 상영 스케줄을 감시해, 감시 대상 상영관에 새 회차가 열리면 ntfy.sh 푸시 알림을 보낸다.
GitHub Actions가 5분마다 [monitor.py](monitor.py)를 실행하고, 상태(state.json)는 저장소에 커밋해 유지한다.

## 동작 방식

1. 오늘부터 21일치 스케줄을 API로 조회 (`SCHEDULE_API` 시크릿의 URL 템플릿 사용)
2. 감시 대상 상영관 등급의 회차만 필터
3. `state.json`(회차 키 목록)과 비교해 **신규 회차만** ntfy로 발송 (첫 실행은 알림 없이 상태만 저장)
4. 오픈 이력은 `openings.log`에 누적 (감지시각·상영일·시작시각만 기록)

## 설정

### 1. ntfy 앱 구독 (가입 불필요)

1. 폰에 **ntfy** 앱 설치 ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) / [iOS](https://apps.apple.com/us/app/ntfy/id1625396347))
2. 앱에서 **+ → Subscribe to topic** → 토픽명 입력 (토픽명이 곧 비밀번호 — 추측 불가능한 이름을 쓸 것)

### 2. GitHub Secrets

Settings → Secrets and variables → Actions:

| Secret | 값 |
|---|---|
| `SCHEDULE_API` | 스케줄 API URL 템플릿 (`{ymd}` 자리에 날짜가 들어감) |
| `SITE_LABEL` | 알림 제목에 표시할 극장 이름 |
| `BOOKING_URL` | 알림 탭 시 열 예매 페이지 URL |
| `NTFY_TOPIC` | 구독한 ntfy 토픽명 |

## 로컬 테스트

환경변수를 설정하고 `python monitor.py` 실행. `NTFY_TOPIC` 없이 실행하면 전송 없이 콘솔 출력만 하는 테스트 모드로 동작한다.
