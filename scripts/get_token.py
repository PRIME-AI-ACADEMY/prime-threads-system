#!/usr/bin/env python3
"""
Помощник для получения токена Threads API. Три шага, без сервера и без curl.

    python3 get_token.py url      --app-id 123 --redirect https://localhost/
        -> печатает ссылку, которую надо открыть в браузере и подтвердить доступ

    python3 get_token.py exchange --app-id 123 --secret ABC \
                                  --redirect https://localhost/ --code AQB...
        -> короткий токен (1 час) + user_id, сразу меняет на долгий (60 дней)
        -> печатает готовые строки для ~/Claude/threads/.env

    python3 get_token.py refresh  --token <долгий токен>
        -> продлевает ещё на 60 дней (можно с 24-го часа жизни токена)

Секрет приложения нигде не сохраняется — используется только в момент обмена.
"""
import argparse, json, sys, urllib.parse, urllib.request, urllib.error

SCOPES = ("threads_basic,threads_content_publish,threads_manage_replies,"
          "threads_read_replies,threads_manage_insights")


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit("Ошибка Meta: " + e.read().decode(errors="replace"))


def post(url, data):
    body = urllib.parse.urlencode(data).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit("Ошибка Meta: " + e.read().decode(errors="replace"))


def cmd_url(a):
    q = urllib.parse.urlencode({
        "client_id": a.app_id,
        "redirect_uri": a.redirect,
        "scope": a.scope,
        "response_type": "code",
    })
    print("\n1. Открой эту ссылку в браузере, где ты залогинена в нужный Threads-аккаунт:\n")
    print(f"https://threads.net/oauth/authorize?{q}\n")
    print("2. Подтверди доступ. Браузер уйдёт на страницу-ошибку — это нормально.")
    print("3. Скопируй из адресной строки значение code=... (без хвоста #_)\n")


def cmd_exchange(a):
    code = a.code.split("#")[0].strip()
    short = post("https://graph.threads.net/oauth/access_token", {
        "client_id": a.app_id,
        "client_secret": a.secret,
        "grant_type": "authorization_code",
        "redirect_uri": a.redirect,
        "code": code,
    })
    token, uid = short.get("access_token"), str(short.get("user_id", ""))
    if not token:
        sys.exit("Не пришёл короткий токен: " + json.dumps(short, ensure_ascii=False))
    long = get("https://graph.threads.net/access_token?" + urllib.parse.urlencode({
        "grant_type": "th_exchange_token",
        "client_secret": a.secret,
        "access_token": token,
    }))
    lt = long.get("access_token")
    if not lt:
        sys.exit("Не пришёл долгий токен: " + json.dumps(long, ensure_ascii=False))
    me = get(f"https://graph.threads.net/v1.0/me?fields=id,username&access_token={lt}")
    print("\nГотово. Впиши это в ~/Claude/threads/.env :\n")
    print(f"THREADS_ACCESS_TOKEN={lt}")
    print(f"THREADS_USER_ID={me.get('id', uid)}")
    print(f"\nАккаунт: @{me.get('username')}")
    print(f"Токен живёт: {long.get('expires_in', 0) // 86400} дней")
    print("\nЭти же две строки положи в GitHub -> Settings -> Secrets and variables -> Actions.\n")


def cmd_refresh(a):
    r = get("https://graph.threads.net/refresh_access_token?" + urllib.parse.urlencode({
        "grant_type": "th_refresh_token", "access_token": a.token,
    }))
    print(f"\nTHREADS_ACCESS_TOKEN={r.get('access_token')}")
    print(f"Продлён на {r.get('expires_in', 0) // 86400} дней.")
    print("Не забудь обновить и .env, и GitHub Secrets.\n")


def main():
    ap = argparse.ArgumentParser(description="Токен Threads API за три шага")
    s = ap.add_subparsers(dest="cmd", required=True)
    p = s.add_parser("url"); p.add_argument("--app-id", required=True)
    p.add_argument("--redirect", default="https://localhost/"); p.add_argument("--scope", default=SCOPES)
    p.set_defaults(fn=cmd_url)
    p = s.add_parser("exchange"); p.add_argument("--app-id", required=True)
    p.add_argument("--secret", required=True); p.add_argument("--redirect", default="https://localhost/")
    p.add_argument("--code", required=True); p.set_defaults(fn=cmd_exchange)
    p = s.add_parser("refresh"); p.add_argument("--token", required=True); p.set_defaults(fn=cmd_refresh)
    a = ap.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
