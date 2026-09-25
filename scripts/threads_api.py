#!/usr/bin/env python3
"""
Threads Graph API — тонкий клиент без зависимостей (только stdlib).

Токен и user-id берутся из окружения или из файла .env рабочей папки:
    THREADS_ACCESS_TOKEN=...
    THREADS_USER_ID=...

Использование:
    python3 threads_api.py limits
    python3 threads_api.py post --text "..."
    python3 threads_api.py post --text "..." --image https://...
    python3 threads_api.py post --text "..." --video https://...
    python3 threads_api.py thread --file thread.txt        # посты разделены строкой ---
    python3 threads_api.py reply --to <media_id> --text "..."
    python3 threads_api.py replies --to <media_id>
    python3 threads_api.py mine --limit 25
    python3 threads_api.py insights --media <media_id>
    python3 threads_api.py account-insights --since 2026-09-01

Все команды печатают JSON в stdout. Ничего не публикуется без явной команды.
"""
import argparse, json, os, sys, time, urllib.parse, urllib.request, urllib.error

BASE = "https://graph.threads.net/v1.0"


ROOT = os.environ.get("THREADS_HOME", os.path.expanduser("~/Claude/threads"))


def load_env():
    """Читает .env из текущей папки и из рабочей папки ($THREADS_HOME, по умолчанию ~/Claude/threads/), не перетирая окружение."""
    for path in (".env", os.path.join(ROOT, ".env")):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def creds():
    load_env()
    token = os.environ.get("THREADS_ACCESS_TOKEN")
    uid = os.environ.get("THREADS_USER_ID")
    if not token or not uid:
        sys.exit("Нет THREADS_ACCESS_TOKEN / THREADS_USER_ID. Это продвинутый режим — смотри GRAPH-API.md. Для публикации через Postiz этот скрипт не нужен.")
    return token, uid


def call(method, path, params=None, retries=3):
    token, _ = creds()
    params = dict(params or {})
    params["access_token"] = token
    url = f"{BASE}/{path.lstrip('/')}"
    data = None
    if method == "POST":
        data = urllib.parse.urlencode(params).encode()
    else:
        url += "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, method=method)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            # 4 = app rate limit, 613 = calls exceeded — ждём и пробуем ещё раз
            if e.code in (429, 500, 503) and attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            sys.exit(json.dumps({"error": True, "status": e.code, "body": body}, ensure_ascii=False))
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            sys.exit(json.dumps({"error": True, "reason": str(e)}, ensure_ascii=False))


def wait_ready(container_id, timeout=300):
    """Видео и карусели обрабатываются асинхронно — ждём FINISHED."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = call("GET", container_id, {"fields": "status,error_message"})
        status = st.get("status")
        if status == "FINISHED":
            return True
        if status in ("ERROR", "EXPIRED"):
            sys.exit(json.dumps({"error": True, "container": container_id, "detail": st}, ensure_ascii=False))
        time.sleep(5)
    sys.exit(json.dumps({"error": True, "reason": "timeout waiting for container", "container": container_id}))


def create_container(uid, text=None, image=None, video=None, reply_to=None,
                     carousel_item=False, children=None, reply_control=None, link=None):
    p = {}
    if children:
        p["media_type"] = "CAROUSEL"
        p["children"] = ",".join(children)
    elif video:
        p["media_type"] = "VIDEO"
        p["video_url"] = video
    elif image:
        p["media_type"] = "IMAGE"
        p["image_url"] = image
    else:
        p["media_type"] = "TEXT"
    if text:
        p["text"] = text
    if carousel_item:
        p["is_carousel_item"] = "true"
    if reply_to:
        p["reply_to_id"] = reply_to
    if reply_control:
        p["reply_control"] = reply_control  # everyone | accounts_you_follow | mentioned_only
    if link:
        p["link_attachment"] = link
    return call("POST", f"{uid}/threads", p)["id"]


def publish(uid, container_id):
    return call("POST", f"{uid}/threads_publish", {"creation_id": container_id})


def cmd_post(a):
    _, uid = creds()
    cid = create_container(uid, text=a.text, image=a.image, video=a.video,
                           reply_to=a.reply_to, reply_control=a.reply_control, link=a.link)
    if a.video or a.image:
        wait_ready(cid)
    else:
        time.sleep(2)
    out = publish(uid, cid)
    print(json.dumps({"published": True, "id": out.get("id"), "container": cid}, ensure_ascii=False))


def cmd_carousel(a):
    _, uid = creds()
    kids = []
    for url in a.images:
        kid = create_container(uid, image=url, carousel_item=True)
        kids.append(kid)
    for kid in kids:
        wait_ready(kid)
    cid = create_container(uid, text=a.text, children=kids)
    wait_ready(cid)
    out = publish(uid, cid)
    print(json.dumps({"published": True, "id": out.get("id"), "children": kids}, ensure_ascii=False))


def cmd_thread(a):
    """Публикует цепочку: каждый следующий пост — ответ на предыдущий."""
    _, uid = creds()
    raw = open(a.file, encoding="utf-8").read() if a.file else a.text
    parts = [p.strip() for p in raw.split("\n---\n") if p.strip()]
    ids, prev = [], None
    for i, part in enumerate(parts):
        if len(part) > 500:
            sys.exit(json.dumps({"error": True, "reason": f"пост {i+1} длиннее 500 знаков ({len(part)})"}, ensure_ascii=False))
        cid = create_container(uid, text=part, reply_to=prev)
        time.sleep(2)
        res = publish(uid, cid)
        prev = res.get("id")
        ids.append(prev)
        if i < len(parts) - 1:
            time.sleep(a.gap)
    print(json.dumps({"published": True, "ids": ids, "count": len(ids)}, ensure_ascii=False))


def cmd_reply(a):
    _, uid = creds()
    cid = create_container(uid, text=a.text, reply_to=a.to, image=a.image)
    time.sleep(2)
    out = publish(uid, cid)
    print(json.dumps({"published": True, "id": out.get("id")}, ensure_ascii=False))


def cmd_replies(a):
    fields = "id,text,username,timestamp,has_replies,hide_status,replied_to"
    print(json.dumps(call("GET", f"{a.to}/replies", {"fields": fields, "reverse": "false"}), ensure_ascii=False, indent=2))


def cmd_mine(a):
    fields = "id,media_type,text,permalink,timestamp,is_quote_post"
    p = {"fields": fields, "limit": a.limit}
    if a.since:
        p["since"] = a.since
    print(json.dumps(call("GET", f"{creds()[1]}/threads", p), ensure_ascii=False, indent=2))


def cmd_insights(a):
    metric = "views,likes,replies,reposts,quotes,shares"
    print(json.dumps(call("GET", f"{a.media}/insights", {"metric": metric}), ensure_ascii=False, indent=2))


def cmd_account_insights(a):
    metric = "views,likes,replies,reposts,quotes,followers_count"
    p = {"metric": metric}
    if a.since:
        p["since"] = a.since
    if a.until:
        p["until"] = a.until
    print(json.dumps(call("GET", f"{creds()[1]}/threads_insights", p), ensure_ascii=False, indent=2))


def cmd_limits(a):
    f = "quota_usage,config,reply_quota_usage,reply_config"
    print(json.dumps(call("GET", f"{creds()[1]}/threads_publishing_limit", {"fields": f}), ensure_ascii=False, indent=2))


def cmd_me(a):
    f = "id,username,threads_profile_picture_url,threads_biography"
    print(json.dumps(call("GET", f"{creds()[1]}", {"fields": f}), ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="Threads Graph API client")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("post"); p.add_argument("--text"); p.add_argument("--image"); p.add_argument("--video")
    p.add_argument("--reply-to", dest="reply_to"); p.add_argument("--reply-control", dest="reply_control")
    p.add_argument("--link"); p.set_defaults(fn=cmd_post)

    p = sub.add_parser("carousel"); p.add_argument("--text"); p.add_argument("--images", nargs="+", required=True)
    p.set_defaults(fn=cmd_carousel)

    p = sub.add_parser("thread"); p.add_argument("--file"); p.add_argument("--text")
    p.add_argument("--gap", type=int, default=3); p.set_defaults(fn=cmd_thread)

    p = sub.add_parser("reply"); p.add_argument("--to", required=True); p.add_argument("--text", required=True)
    p.add_argument("--image"); p.set_defaults(fn=cmd_reply)

    p = sub.add_parser("replies"); p.add_argument("--to", required=True); p.set_defaults(fn=cmd_replies)

    p = sub.add_parser("mine"); p.add_argument("--limit", type=int, default=25); p.add_argument("--since")
    p.set_defaults(fn=cmd_mine)

    p = sub.add_parser("insights"); p.add_argument("--media", required=True); p.set_defaults(fn=cmd_insights)

    p = sub.add_parser("account-insights"); p.add_argument("--since"); p.add_argument("--until")
    p.set_defaults(fn=cmd_account_insights)

    sub.add_parser("limits").set_defaults(fn=cmd_limits)
    sub.add_parser("me").set_defaults(fn=cmd_me)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
