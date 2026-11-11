"""배포한 웹사이트 가동 상태 점검기.

sites.json의 사이트를 한 번 점검하고 docs/data/ 아래에 결과를 기록한다.
GitHub Actions가 5분마다 실행하며, 표준 라이브러리만 쓴다.

환경변수(선택)
  TELEGRAM_TOKEN, TELEGRAM_CHAT_ID  다운/복구 알림
  GOATCOUNTER_TOKEN                 방문자 통계(sites.json의 goatcounter 코드와 함께)
"""
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "docs", "data")
STATUS_FILE = os.path.join(DATA, "status.json")
HISTORY_FILE = os.path.join(DATA, "history.json")

TIMEOUT = 15          # 초
SLOW_MS = 3000        # 이보다 느리면 '느림'
KEEP_DAYS = 7         # 응답 기록 보관 기간
MAX_INCIDENTS = 30
UA = "site-monitor/1.0 (+uptime check)"


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def probe(url):
    """(HTTP 코드 또는 None, 응답시간 ms 또는 None, 오류 메시지)"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            r.read(65536)
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except (urllib.error.URLError, socket.timeout, ConnectionError, ssl.SSLError) as e:
        reason = getattr(e, "reason", e)
        return None, None, str(reason)[:160]
    ms = round((time.perf_counter() - start) * 1000)
    return code, ms, "" if code < 400 else f"HTTP {code}"


def check(url):
    code, ms, err = probe(url)
    if code is None or code >= 400:   # 일시적 오류를 걸러내려고 한 번 더 시도
        time.sleep(5)
        code, ms, err = probe(url)
    return code, ms, err


def ssl_days_left(url):
    p = urllib.parse.urlparse(url)
    if p.scheme != "https":
        return None
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((p.hostname, p.port or 443), timeout=TIMEOUT) as s:
            with ctx.wrap_socket(s, server_hostname=p.hostname) as ss:
                exp = ssl.cert_time_to_seconds(ss.getpeercert()["notAfter"])
        return int((exp - time.time()) // 86400)
    except Exception:
        return None


def visitors(code):
    """GoatCounter 최근 7일 일별 방문 수. 설정이 없거나 실패하면 None."""
    token = os.environ.get("GOATCOUNTER_TOKEN")
    if not code or not token:
        return None
    end = now()
    start = end - timedelta(days=7)
    q = urllib.parse.urlencode({"start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")})
    req = urllib.request.Request(f"https://{code}.goatcounter.com/api/v0/stats/total?{q}",
                                 headers={"Authorization": f"Bearer {token}", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = json.loads(r.read())
    except Exception as e:
        print(f"  ! GoatCounter {code}: {e}")
        return None
    daily = [{"day": s.get("day"), "count": s.get("daily", 0)} for s in body.get("stats", [])]
    return {"total7d": body.get("total", sum(d["count"] for d in daily)), "daily": daily}


def telegram(text):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("  (텔레그램 설정 없음, 알림 생략)")
        return
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=TIMEOUT)
    except Exception as e:
        print(f"  ! 텔레그램 전송 실패: {e}")


def duration(sec):
    sec = int(sec)
    if sec < 3600:
        return f"{max(1, sec // 60)}분"
    if sec < 86400:
        return f"{sec // 3600}시간 {sec % 3600 // 60}분"
    return f"{sec // 86400}일 {sec % 86400 // 3600}시간"


def uptime(points, since):
    pts = [p for p in points if p[0] >= since]
    if not pts:
        return None
    return round(100 * sum(1 for p in pts if p[2]) / len(pts), 2)


def main():
    sites = load(os.path.join(ROOT, "sites.json"), [])
    status = load(STATUS_FILE, {"sites": {}, "incidents": []})
    history = load(HISTORY_FILE, {})
    t = now()
    ts = int(t.timestamp())
    cutoff = ts - KEEP_DAYS * 86400
    hour_check = t.minute < 10   # SSL·방문자는 매시 첫 실행에만

    for site in sites:
        name, url = site["name"], site["url"]
        code, ms, err = check(url)
        up = code is not None and code < 400
        prev = status["sites"].get(name, {})
        was_up = prev.get("up", True)

        # 기록: [시각, 응답ms 또는 0, 정상 여부 1/0]
        pts = [p for p in history.get(name, []) if p[0] >= cutoff]
        pts.append([ts, ms or 0, 1 if up else 0])
        history[name] = pts

        since = prev.get("since", iso(t)) if was_up == up and prev else iso(t)
        cur = {
            "name": name, "url": url, "up": up, "code": code, "ms": ms, "error": err,
            "slow": bool(up and ms and ms > SLOW_MS), "since": since, "checked": iso(t),
            "uptime24h": uptime(pts, ts - 86400), "uptime7d": uptime(pts, cutoff),
            "sslDays": prev.get("sslDays"), "visitors": prev.get("visitors"),
        }
        if hour_check or "sslDays" not in prev or (site.get("goatcounter") and not prev.get("visitors")):
            cur["sslDays"] = ssl_days_left(url)
            v = visitors(site.get("goatcounter"))
            if v is not None:
                cur["visitors"] = v

        # 상태가 바뀌면 사고 기록 + 알림
        if was_up and not up:
            status["incidents"].insert(0, {"site": name, "start": iso(t), "end": None, "reason": err})
            telegram(f"🔴 다운: {name}\n{url}\n원인: {err}")
        elif not was_up and up:
            for inc in status["incidents"]:
                if inc["site"] == name and inc["end"] is None:
                    inc["end"] = iso(t)
                    break
            down_for = (t - datetime.strptime(prev["since"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds()
            telegram(f"🟢 복구: {name}\n{url}\n다운 시간: {duration(down_for)}")
        today = t.strftime("%Y-%m-%d")
        cur["sslWarned"] = prev.get("sslWarned")
        if cur["sslDays"] is not None and cur["sslDays"] <= 14 and cur["sslWarned"] != today:
            cur["sslWarned"] = today   # 하루 한 번만
            telegram(f"⚠️ SSL 인증서 만료 {cur['sslDays']}일 전: {name}")

        status["sites"][name] = cur
        mark = "UP  " if up else "DOWN"
        print(f"{mark} {name:30} {code} {ms}ms {err}")

    names = {s["name"] for s in sites}
    status["sites"] = {k: v for k, v in status["sites"].items() if k in names}
    history = {k: v for k, v in history.items() if k in names}
    status["incidents"] = status["incidents"][:MAX_INCIDENTS]
    status["order"] = [s["name"] for s in sites]
    status["updated"] = iso(t)
    save(STATUS_FILE, status)
    save(HISTORY_FILE, history)


if __name__ == "__main__":
    main()
