#!/usr/bin/env python3
"""
Банк медиа для Threads: забирает фото и видео с компьютера, нормализует под
требования Graph API, чистит EXIF и выкладывает в публичный CDN.

Зачем: Threads Graph API принимает только ПУБЛИЧНЫЕ URL. Локальный файл с рабочего
стола опубликовать нельзя. И облачная публикация (когда ноутбук закрыт) тем более
не видит твой диск. Поэтому медиа заливается заранее, а в очереди лежит ссылка.

Конфиг ~/Claude/threads/media.config.json:
{
  "repo_path": "/Users/.../Claude/threads-cloud",   # локальная копия публичного репо
  "repo_slug": "PRIME-AI-ACADEMY/threads-cloud",    # owner/repo для CDN-ссылки
  "branch": "main",
  "cdn": "jsdelivr"                                  # jsdelivr | raw | custom
}

Команды:
    python3 media_bank.py scan
    python3 media_bank.py ingest [--tags скрин,дашборд] [--note "..."] [--source ~/Desktop]
    python3 media_bank.py list [--kind image|video] [--unused]
    python3 media_bank.py pick --tags скрин --kind image
    python3 media_bank.py use --id m-0007 --post smoke-1
    python3 media_bank.py push
"""
import argparse, datetime as dt, hashlib, json, os, shutil, subprocess, sys

ROOT = os.environ.get("THREADS_HOME", os.path.expanduser("~/Claude/threads"))
INBOX = os.path.join(ROOT, "inbox")
INDEX = os.path.join(ROOT, "bank", "media.jsonl")
CONFIG = os.path.join(ROOT, "media.config.json")

IMG_EXT = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
VID_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}

# Требования Threads Graph API
IMG_MAX_PX = 2000          # шире не нужно, лента всё равно сожмёт
IMG_MAX_MB = 8
VID_MAX_MB = 20            # предел файла для jsDelivr; для Threads этого хватает с запасом
VID_MAX_SEC = 300


def cfg():
    if not os.path.exists(CONFIG):
        sys.exit(f"Нет {CONFIG}. Скилл threads-media-bank создаёт его на первом запуске.")
    return json.load(open(CONFIG, encoding="utf-8"))


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def read_index():
    if not os.path.exists(INDEX):
        return []
    return [json.loads(l) for l in open(INDEX, encoding="utf-8") if l.strip()]


def write_index(items):
    os.makedirs(os.path.dirname(INDEX), exist_ok=True)
    with open(INDEX, "w", encoding="utf-8") as fh:
        for i in items:
            fh.write(json.dumps(i, ensure_ascii=False) + "\n")


def cdn_url(c, relpath):
    slug, branch = c["repo_slug"], c.get("branch", "main")
    mode = c.get("cdn", "jsdelivr")
    if mode == "jsdelivr":
        return f"https://cdn.jsdelivr.net/gh/{slug}@{branch}/{relpath}"
    if mode == "raw":
        return f"https://raw.githubusercontent.com/{slug}/{branch}/{relpath}"
    return c["cdn_base"].rstrip("/") + "/" + relpath


def probe_duration(path):
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", path])
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def norm_image(src, dst):
    """Ресайз + перекодирование в JPEG. -map_metadata -1 срезает EXIF, включая геолокацию."""
    r = sh(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
            "-vf", f"scale='min({IMG_MAX_PX},iw)':-2",
            "-map_metadata", "-1", "-q:v", "3", dst])
    if r.returncode != 0:
        return False, r.stderr[-300:]
    if os.path.getsize(dst) > IMG_MAX_MB * 1024 * 1024:
        sh(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
            "-vf", f"scale='min(1440,iw)':-2", "-map_metadata", "-1", "-q:v", "6", dst])
    return True, None


def norm_video(src, dst):
    """H.264/AAC, вертикаль до 1080, 30 fps, метаданные срезаны, подгонка под лимит размера."""
    dur = probe_duration(src)
    if dur > VID_MAX_SEC:
        return False, f"длиннее {VID_MAX_SEC} с ({int(dur)} с) — нарежь на куски"
    for crf, width in ((23, 1080), (26, 1080), (28, 720)):
        r = sh(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                "-vf", f"scale='min({width},iw)':-2,fps=30", "-map_metadata", "-1",
                "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                "-c:a", "aac", "-b:a", "128k", dst])
        if r.returncode != 0:
            return False, r.stderr[-300:]
        if os.path.getsize(dst) <= VID_MAX_MB * 1024 * 1024:
            return True, None
    return False, f"не ужимается до {VID_MAX_MB} МБ — укороти клип"


def cmd_scan(a):
    os.makedirs(INBOX, exist_ok=True)
    src = os.path.expanduser(a.source) if a.source else INBOX
    files = []
    for name in sorted(os.listdir(src)):
        p = os.path.join(src, name)
        ext = os.path.splitext(name)[1].lower()
        if os.path.isfile(p) and (ext in IMG_EXT or ext in VID_EXT):
            files.append({"file": name, "kind": "image" if ext in IMG_EXT else "video",
                          "mb": round(os.path.getsize(p) / 1048576, 2)})
    print(json.dumps({"source": src, "found": len(files), "files": files},
                     ensure_ascii=False, indent=2))


def cmd_ingest(a):
    c = cfg()
    media_dir = os.path.join(c["repo_path"], "media")
    os.makedirs(media_dir, exist_ok=True)
    os.makedirs(INBOX, exist_ok=True)
    src_dir = os.path.expanduser(a.source) if a.source else INBOX
    index = read_index()
    known = {i["sha"] for i in index}
    added, skipped = [], []
    for name in sorted(os.listdir(src_dir)):
        src = os.path.join(src_dir, name)
        ext = os.path.splitext(name)[1].lower()
        if not os.path.isfile(src) or (ext not in IMG_EXT and ext not in VID_EXT):
            continue
        sha = hashlib.sha1(open(src, "rb").read()).hexdigest()[:12]
        if sha in known:
            skipped.append({"file": name, "why": "уже в банке"})
            continue
        kind = "image" if ext in IMG_EXT else "video"
        mid = f"m-{sha}"
        out_ext = ".jpg" if kind == "image" else ".mp4"
        rel = f"media/{mid}{out_ext}"
        dst = os.path.join(c["repo_path"], rel)
        ok, err = (norm_image if kind == "image" else norm_video)(src, dst)
        if not ok:
            skipped.append({"file": name, "why": err})
            if os.path.exists(dst):
                os.remove(dst)
            continue
        rec = {"id": mid, "sha": sha, "kind": kind, "path": rel,
               "url": cdn_url(c, rel), "orig": name,
               "mb": round(os.path.getsize(dst) / 1048576, 2),
               "tags": [t.strip() for t in (a.tags or "").split(",") if t.strip()],
               "note": a.note or "", "used_in": [],
               "added": dt.datetime.now().astimezone().isoformat()}
        if kind == "video":
            rec["sec"] = round(probe_duration(dst), 1)
        index.append(rec)
        added.append(rec)
        if a.move:
            os.makedirs(os.path.join(INBOX, "_done"), exist_ok=True)
            shutil.move(src, os.path.join(INBOX, "_done", name))
    write_index(index)
    print(json.dumps({"added": len(added), "skipped": skipped,
                      "new": [{"id": r["id"], "kind": r["kind"], "mb": r["mb"], "url": r["url"]} for r in added],
                      "next": "python3 media_bank.py push  — выложить в CDN"},
                     ensure_ascii=False, indent=2))


def cmd_list(a):
    items = read_index()
    if a.kind:
        items = [i for i in items if i["kind"] == a.kind]
    if a.unused:
        items = [i for i in items if not i.get("used_in")]
    for i in items:
        used = f"использовано {len(i.get('used_in', []))}×" if i.get("used_in") else "свободно"
        print(f"{i['id']:16} {i['kind']:6} {i['mb']:>6} МБ  {used:16} {','.join(i.get('tags', [])):24} {i.get('note','')[:40]}")
    print(f"\nвсего: {len(items)}")


def cmd_pick(a):
    """Подбирает наименее использованное медиа под теги — чтобы банк не крутил одну картинку."""
    want = {t.strip().lower() for t in (a.tags or "").split(",") if t.strip()}
    items = [i for i in read_index() if not a.kind or i["kind"] == a.kind]
    scored = []
    for i in items:
        tags = {t.lower() for t in i.get("tags", [])}
        overlap = len(want & tags)
        if want and not overlap:
            continue
        scored.append((overlap, -len(i.get("used_in", [])), i))
    if not scored:
        print(json.dumps({"found": False, "hint": "нет подходящего медиа — постим текстом или пополни банк"},
                         ensure_ascii=False)); return
    scored.sort(key=lambda x: (-x[0], -x[1]))
    best = scored[0][2]
    print(json.dumps({"found": True, "id": best["id"], "url": best["url"],
                      "kind": best["kind"], "tags": best.get("tags", [])}, ensure_ascii=False, indent=2))


def cmd_use(a):
    items = read_index(); n = 0
    for i in items:
        if i["id"] == a.id:
            i.setdefault("used_in", []).append({"post": a.post, "at": dt.datetime.now().astimezone().isoformat()})
            n += 1
    write_index(items)
    print(json.dumps({"updated": n}, ensure_ascii=False))


def cmd_push(a):
    c = cfg(); repo = c["repo_path"]
    if not os.path.isdir(os.path.join(repo, ".git")):
        sys.exit(f"{repo} — не git-репозиторий. Смотри CLOUD.md, шаг 1.")
    sh(["git", "add", "-A"], cwd=repo)
    st = sh(["git", "status", "--porcelain"], cwd=repo)
    if not st.stdout.strip():
        print(json.dumps({"pushed": False, "why": "нечего коммитить"}, ensure_ascii=False)); return
    msg = f"media+queue {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}"
    sh(["git", "commit", "-m", msg], cwd=repo)
    r = sh(["git", "push"], cwd=repo)
    if r.returncode != 0:
        sys.exit(json.dumps({"pushed": False, "error": r.stderr[-400:]}, ensure_ascii=False))
    print(json.dumps({"pushed": True, "note": "jsDelivr подхватывает новые файлы за 1–10 минут"},
                     ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="Банк медиа Threads")
    s = ap.add_subparsers(dest="cmd", required=True)
    p = s.add_parser("scan"); p.add_argument("--source"); p.set_defaults(fn=cmd_scan)
    p = s.add_parser("ingest"); p.add_argument("--tags"); p.add_argument("--note")
    p.add_argument("--source"); p.add_argument("--move", action="store_true", default=True)
    p.set_defaults(fn=cmd_ingest)
    p = s.add_parser("list"); p.add_argument("--kind"); p.add_argument("--unused", action="store_true")
    p.set_defaults(fn=cmd_list)
    p = s.add_parser("pick"); p.add_argument("--tags"); p.add_argument("--kind"); p.set_defaults(fn=cmd_pick)
    p = s.add_parser("use"); p.add_argument("--id", required=True); p.add_argument("--post", required=True)
    p.set_defaults(fn=cmd_use)
    s.add_parser("push").set_defaults(fn=cmd_push)
    a = ap.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
