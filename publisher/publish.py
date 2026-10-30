#!/usr/bin/env python3
"""PLATINUM Portugal — publishes due posts from calendar.json to Instagram and the Facebook Page.

Modes:
  check     validate secrets, token, Instagram account and every media URL; publishes nothing
  dry-run   list what would be published right now; publishes nothing
  run       publish every post that is due (default)
  --only N  publish post N now, whatever its date (still skips hold=true and already-published platforms)

Env: META_PAGE_TOKEN, FB_PAGE_ID, IG_USER_ID (secrets) · MEDIA_BASE_URL (variable, e.g. https://user.github.io/repo)
Optional: PLATFORMS=ig,fb (default both) · GRAPH_VERSION=v26.0 · MAX_LATE_HOURS=36
Standard library only.
"""
import json, os, sys, time, datetime as dt, urllib.request, urllib.parse, urllib.error
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAL = os.path.join(ROOT, "calendar.json")
STATE = os.path.join(ROOT, "state", "published.json")
TZ = ZoneInfo("Europe/Lisbon")
GV = os.environ.get("GRAPH_VERSION", "v26.0")
G = f"https://graph.facebook.com/{GV}"
MAX_LATE = float(os.environ.get("MAX_LATE_HOURS", "36"))

def env(name):
    v = (os.environ.get(name) or "").strip()
    if not v: sys.exit(f"Missing {name}. Add it under Settings → Secrets and variables → Actions.")
    return v

def call(method, url, params=None, headers=None, data=None):
    params = dict(params or {})
    body = None
    if method == "GET":
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    else:
        body = data if data is not None else urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = r.read().decode() or "{}"
            return json.loads(txt)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {url.split('?')[0]} → HTTP {e.code}: {detail[:600]}")

def media_url(base, rel):
    return base.rstrip("/") + "/" + rel.lstrip("/")

def head_ok(url):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status == 200
    except Exception:
        return False

# ---------------- Instagram ----------------
def ig_wait(cid, tok, kind):
    limit = 900 if kind == "reel" else 180
    t0 = time.time()
    while True:
        st = call("GET", f"{G}/{cid}", {"fields": "status_code,status", "access_token": tok})
        code = st.get("status_code")
        if code == "FINISHED": return
        if code in ("ERROR", "EXPIRED"): raise RuntimeError(f"Instagram container {cid}: {st}")
        if time.time() - t0 > limit: raise RuntimeError(f"Instagram container {cid} not ready after {limit}s: {st}")
        time.sleep(10)

def ig_publish(post, base, tok, ig):
    cap = post["caption"]; files = post["files"]
    if post["kind"] == "reel":
        p = {"media_type": "REELS", "video_url": media_url(base, files[0]), "caption": cap,
             "share_to_feed": "true", "access_token": tok}
        if post.get("cover"): p["cover_url"] = media_url(base, post["cover"])
        cid = call("POST", f"{G}/{ig}/media", p)["id"]; ig_wait(cid, tok, "reel")
    elif post["kind"] == "carousel":
        kids = []
        for f in files:
            k = call("POST", f"{G}/{ig}/media", {"image_url": media_url(base, f), "is_carousel_item": "true", "access_token": tok})["id"]
            ig_wait(k, tok, "image"); kids.append(k)
        cid = call("POST", f"{G}/{ig}/media", {"media_type": "CAROUSEL", "children": ",".join(kids), "caption": cap, "access_token": tok})["id"]
        ig_wait(cid, tok, "carousel")
    else:
        cid = call("POST", f"{G}/{ig}/media", {"image_url": media_url(base, files[0]), "caption": cap, "access_token": tok})["id"]
        ig_wait(cid, tok, "image")
    return call("POST", f"{G}/{ig}/media_publish", {"creation_id": cid, "access_token": tok})["id"]

# ---------------- Facebook Page ----------------
def fb_publish(post, base, tok, page):
    cap = post["caption"]; files = post["files"]
    if post["kind"] == "reel":
        start = call("POST", f"{G}/{page}/video_reels", {"upload_phase": "start", "access_token": tok})
        vid = start["video_id"]; up = start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{GV}/{vid}"
        call("POST", up, headers={"Authorization": f"OAuth {tok}", "file_url": media_url(base, files[0])}, data=b"")
        call("POST", f"{G}/{page}/video_reels", {"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                                                  "description": cap, "access_token": tok})
        return vid
    if post["kind"] == "carousel":
        ids = [call("POST", f"{G}/{page}/photos", {"url": media_url(base, f), "published": "false", "access_token": tok})["id"] for f in files]
        p = {"message": cap, "access_token": tok}
        for i, x in enumerate(ids): p[f"attached_media[{i}]"] = json.dumps({"media_fbid": x})
        return call("POST", f"{G}/{page}/feed", p)["id"]
    return call("POST", f"{G}/{page}/photos", {"url": media_url(base, files[0]), "message": cap, "access_token": tok})["id"]

# ---------------- main ----------------
def when(post):
    d = dt.date.fromisoformat(post["date"]); h, m = map(int, post["time"].split(":"))
    return dt.datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)

def main():
    args = sys.argv[1:]
    mode = "run"
    only = None
    if args and args[0] in ("check", "dry-run", "run", "only"): mode = args.pop(0)
    if mode == "only": mode = "run"
    if "--only" in args: only = int(args[args.index("--only") + 1])
    cal = json.load(open(CAL, encoding="utf-8"))
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    plats = [p.strip() for p in os.environ.get("PLATFORMS", "ig,fb").split(",") if p.strip()]
    tok, page, ig = env("META_PAGE_TOKEN"), env("FB_PAGE_ID"), env("IG_USER_ID")
    base = env("MEDIA_BASE_URL")
    if not base.startswith("https://") or "\n" in base:
        sys.exit("FAIL Media hosting: MEDIA_BASE_URL must start with https:// and contain .github.io, e.g. https://user.github.io/repo")
    now = dt.datetime.now(TZ)

    if mode == "check":
        fails = 0
        def ok(label, fn):
            try:
                print(f"OK   {label}: {fn()}")
            except Exception as e:
                print(f"FAIL {label}: {e}"); return 1
            return 0
        fails += ok("Page", lambda: (lambda me: me["name"] + ("" if str(me["id"]) == page else
                     f"  (WARNING: id {me['id']} is not FB_PAGE_ID {page}: use the Page access_token from me/accounts)"))(
                     call("GET", f"{G}/me", {"fields": "id,name", "access_token": tok})))
        fails += ok("Instagram account", lambda: "@" + call("GET", f"{G}/{ig}", {"fields": "username", "access_token": tok})["username"])
        fails += ok("Publishing quota", lambda: json.dumps(call("GET", f"{G}/{ig}/content_publishing_limit",
                     {"fields": "quota_usage,config", "access_token": tok}).get("data", [{}])[0]))
        def media():
            files = [f for p in cal for f in p["files"] + ([p["cover"]] if p.get("cover") else [])]
            bad = [media_url(base, f) for f in files if not head_ok(media_url(base, f))]
            if bad: raise RuntimeError(f"{len(bad)} of {len(files)} files unreachable, e.g. {bad[0]}")
            return f"{len(files)} files reachable at {base}"
        fails += ok("Media hosting", media)
        sys.exit(1 if fails else 0)

    due = []
    for p in cal:
        if only is not None and p["n"] != only: continue
        if p.get("hold"):
            if only is not None: print(f"#{p['n']:02d} is on hold: {p.get('hold_reason')}")
            continue
        t = when(p)
        if only is None:
            if t > now: continue
            if (now - t).total_seconds() > MAX_LATE * 3600 and str(p["n"]) not in state:
                print(f"#{p['n']:02d} skipped: more than {MAX_LATE:.0f} h late (publish it with --only {p['n']})"); continue
        todo = [x for x in plats if x not in state.get(str(p["n"]), {})]
        if todo: due.append((p, todo))

    if not due: print(f"{now:%Y-%m-%d %H:%M} Lisbon: nothing due."); return
    failed = 0
    for p, todo in due:
        for plat in todo:
            label = f"#{p['n']:02d} {p['kind']} '{p['title']}' → {plat}"
            if mode == "dry-run": print("would publish", label); continue
            try:
                pid = ig_publish(p, base, tok, ig) if plat == "ig" else fb_publish(p, base, tok, page)
                state.setdefault(str(p["n"]), {})[plat] = {"id": pid, "at": dt.datetime.now(TZ).isoformat(timespec="seconds")}
                print("published", label, "id", pid)
            except Exception as e:
                failed += 1; print("FAILED", label, "—", e)
            os.makedirs(os.path.dirname(STATE), exist_ok=True)
            json.dump(state, open(STATE, "w"), indent=1, ensure_ascii=False)
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
