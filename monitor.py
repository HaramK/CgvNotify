# -*- coding: utf-8 -*-
"""
상영 스케줄 오픈 알리미

- 지정된 스케줄 API를 폴링해서, 감시 대상 상영관에 새 회차가 등장하면 ntfy.sh 푸시를 보낸다.
- 상태(state.json)와 비교해 '신규 회차'만 알린다. 첫 실행은 알림 없이 상태만 저장.
- 필수 환경변수:
    SCHEDULE_API  : 스케줄 API URL 템플릿 ({ymd} 자리에 날짜가 들어감)
    NTFY_TOPIC    : ntfy 토픽명 (없으면 전송 없이 출력만 하는 테스트 모드)
- 선택 환경변수:
    SITE_LABEL    : 알림 제목에 쓸 극장 이름 (기본: "극장")
    BOOKING_URL   : 알림 탭 시 열 예매 페이지 URL
    MOVIE_KEYWORD : 특정 영화만 감시 (기본: 전체)
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

SCHEDULE_API = os.environ.get("SCHEDULE_API", "").strip()
SITE_LABEL = os.environ.get("SITE_LABEL", "극장").strip()
BOOKING_URL = os.environ.get("BOOKING_URL", "").strip()
MOVIE_KEYWORD = os.environ.get("MOVIE_KEYWORD", "").strip()
# 감시 대상 상영관 등급 코드 접두사
TARGET_GRADES = ("03",)
# 예매 오픈 범위(~2주)보다 넓게 잡아야 '감시창에 새로 들어온 날짜'를 오픈으로 오인하지 않는다.
DAYS_AHEAD = 21

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "state.json")
OPENINGS_LOG = os.path.join(BASE_DIR, "openings.log")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
if BOOKING_URL:
    HEADERS["Referer"] = BOOKING_URL

WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def http_get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))


def is_target_screen(row):
    grad = (row.get("scnsGradCd") or "")[:2]
    return grad in TARGET_GRADES


def fetch_showtimes():
    """감시 대상 회차를 {key: info}로 반환. (요청 성공 수, 오류 목록)도 함께."""
    today = datetime.now(KST).date()
    found = {}
    ok = 0
    errors = []
    for d in range(DAYS_AHEAD + 1):
        day = today + timedelta(days=d)
        ymd = day.strftime("%Y%m%d")
        try:
            data = http_get_json(SCHEDULE_API.format(ymd=ymd))
            ok += 1
        except Exception as e:
            # 공개 로그에 URL이 남지 않도록 예외 타입만 기록
            errors.append(f"{ymd}: {type(e).__name__}")
            continue
        for row in (data.get("data") or []):
            if not is_target_screen(row):
                continue
            title = row.get("movNm") or row.get("expoProdNm") or ""
            if MOVIE_KEYWORD and MOVIE_KEYWORD not in title:
                continue
            start = row.get("scnsrtTm") or ""
            key = "|".join([ymd, row.get("scnsNo") or "", row.get("scnSseq") or ""])
            found[key] = {
                "ymd": ymd,
                "weekday": WEEKDAY_KO[day.weekday()],
                "start": f"{start[:2]}:{start[2:]}" if len(start) == 4 else start,
                "title": title,
                "free": int(row.get("frSeatCnt") or 0),
                "total": int(row.get("stcnt") or 0),
            }
        time.sleep(0.3)  # 연속 요청 간 간격
    return found, ok, errors


def load_state():
    """이전에 관측한 회차 키 집합."""
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_state(keys):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(keys), f, indent=0)


def fmt_date(info):
    ymd = info["ymd"]
    return f"{int(ymd[4:6])}/{int(ymd[6:8])}({info['weekday']})"


def build_alert(prev_keys, curr):
    """신규 회차를 영화·날짜별로 묶은 알림 문구를 만든다. 없으면 None."""
    new_keys = [k for k in sorted(curr) if k not in prev_keys]
    if not new_keys:
        return None

    now = datetime.now(KST)
    # 오픈 이력 (패턴 분석용): 감지시각, 상영일, 시작시각만 기록 (제목은 저장소에 남기지 않음)
    with open(OPENINGS_LOG, "a", encoding="utf-8") as f:
        for k in new_keys:
            i = curr[k]
            f.write("\t".join([now.strftime("%Y-%m-%d %H:%M"), i["ymd"], i["start"],
                               f"{i['free']}/{i['total']}"]) + "\n")

    groups = {}  # (title, ymd) -> [info]
    for k in new_keys:
        i = curr[k]
        groups.setdefault((i["title"], i["ymd"]), []).append(i)

    lines = [f"🎬 {SITE_LABEL} 예매 오픈! ({len(new_keys)}회차)"]
    for (title, _ymd), infos in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        infos.sort(key=lambda i: i["start"])
        times = " ".join(i["start"] for i in infos)
        lines.append(f"\n📌 {title}\n{fmt_date(infos[0])} · {times}")
    if BOOKING_URL:
        lines.append(f"\n예매: {BOOKING_URL}")
    return "\n".join(lines)


def send_ntfy(text):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/")
    if not topic:
        print("[테스트 모드] NTFY_TOPIC 미설정 — 전송 생략. 보낼 내용:")
        print(text)
        return
    # 한글 제목/본문을 안전하게 보내기 위해 JSON publish 방식 사용.
    # 첫 줄(🎬 ...)은 제목으로, 나머지는 본문으로 분리
    title, _, body = text.partition("\n")
    payload = {
        "topic": topic,
        "title": title.strip(),
        "message": body.strip() or title.strip(),
        "tags": ["clapper"],
        "priority": 4,
    }
    if BOOKING_URL:
        payload["click"] = BOOKING_URL
    req = urllib.request.Request(server, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as res:
        res.read()
    print("ntfy 전송 완료")


def main():
    if not SCHEDULE_API or "{ymd}" not in SCHEDULE_API:
        print("[오류] SCHEDULE_API 환경변수({ymd} 템플릿 포함)가 필요합니다", file=sys.stderr)
        sys.exit(1)

    curr, ok, errors = fetch_showtimes()
    for e in errors:
        print(f"[경고] 조회 실패 {e}", file=sys.stderr)
    if ok == 0:
        print("[오류] 모든 날짜 조회 실패 — 접근 차단 가능성", file=sys.stderr)
        sys.exit(1)

    prev_keys = load_state()
    first_run = not prev_keys

    if first_run:
        print(f"첫 실행: 현재 {len(curr)}개 회차를 기준 상태로 저장 (알림 생략)")
    else:
        alert = build_alert(prev_keys, curr)
        if alert:
            send_ntfy(alert)
        else:
            print(f"변동 없음 (감시 중인 회차 {len(curr)}개)")

    # 이전 키와 병합 후 지나간 날짜만 정리해 저장.
    # (일시적 조회 실패로 특정 날짜가 비어도, 다음 실행에서 재알림되지 않도록 이전 키를 유지)
    today_ymd = datetime.now(KST).strftime("%Y%m%d")
    merged = prev_keys | set(curr)
    merged = {k for k in merged if k.split("|", 1)[0] >= today_ymd}
    save_state(merged)


if __name__ == "__main__":
    main()
