#!/usr/bin/env python3
"""SoundShelf HTTP service."""
import argparse
import json
import math
import signal
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

PRODUCT = "SoundShelf"
RESOURCE = "tracks"

PAGE = r'''<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SoundShelf · 音频曲目与播放清单</title>
<style>
:root{color-scheme:light dark}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:56rem;margin:2.5rem auto;padding:0 1rem;line-height:1.7}
h1{margin-bottom:.25rem}
.sub{color:#6b7280;margin-top:0}
a{color:#175b9c}
form{border:1px solid #d1d5db;border-radius:.75rem;padding:1rem 1.25rem;margin:1.25rem 0;background:#fafafa}
label{display:block;font-weight:600;margin-top:.75rem}
label .req{color:#b91c1c}
input[type=text],input[type=number],textarea{width:100%;box-sizing:border-box;padding:.5rem .6rem;border:1px solid #9ca3af;border-radius:.5rem;font:inherit;background:#fff;color:#111}
textarea{min-height:5rem;resize:vertical;white-space:pre-wrap}
.hint{font-weight:400;color:#6b7280;font-size:.85rem}
button{margin-top:1rem;padding:.55rem 1.2rem;border:0;border-radius:.5rem;background:#175b9c;color:#fff;font:inherit;cursor:pointer}
button:hover{background:#124a80}
.check{display:flex;align-items:center;gap:.5rem;font-weight:600;margin-top:.75rem}
.check input{width:auto}
.msg{margin-top:1rem;padding:.6rem .8rem;border-radius:.5rem;white-space:pre-wrap}
.msg.err{background:#fee2e2;color:#7f1d1d;border:1px solid #fca5a5}
.msg.ok{background:#dcfce7;color:#14532d;border:1px solid #86efac}
.msg.conflict{background:#fef3c7;color:#78350f;border:1px solid #fcd34d}
table{width:100%;border-collapse:collapse;margin-top:.5rem}
th,td{text-align:left;vertical-align:top;padding:.5rem .6rem;border-bottom:1px solid #e5e7eb}
th{font-size:.85rem;color:#6b7280;font-weight:600}
td.id{white-space:nowrap;color:#6b7280}
.notes{white-space:pre-wrap;word-break:break-word}
.tags{display:flex;flex-wrap:wrap;gap:.3rem}
.tag{background:#e0e7ff;color:#3730a3;border-radius:999px;padding:.05rem .55rem;font-size:.8rem}
.empty{color:#6b7280;padding:1rem 0}
.muted{color:#9ca3af}
.cover-link{word-break:break-all}
</style>
<main>
<h1>SoundShelf</h1>
<p class="sub">音频曲目与播放清单 · 手动收录</p>

<form id="track-form" novalidate>
  <strong>收录曲目</strong>
  <div id="form-error" class="msg err" hidden></div>
  <div id="form-ok" class="msg ok" hidden></div>
  <div id="form-conflict" class="msg conflict" hidden></div>

  <label>名称 <span class="req">*</span>
    <input type="text" name="title" required placeholder="例如：晨间播客第 1 期">
  </label>

  <label>来源 <span class="req">*</span> <span class="hint">网址或本地文件路径，保存时不检查是否可播放</span>
    <input type="text" name="source" required placeholder="例如：https://example.com/audio.mp3 或 /music/track.wav">
  </label>

  <label>时长（秒） <span class="hint">可留空，表示未知；允许 0 与小数</span>
    <input type="number" name="duration" min="0" step="any" placeholder="留空表示未知">
  </label>

  <label>封面地址 <span class="hint">可留空，保存时不检查远端文件是否可访问</span>
    <input type="text" name="cover" placeholder="例如：https://example.com/cover.jpg">
  </label>

  <label>说明 <span class="hint">可留空，保留换行</span>
    <textarea name="notes" placeholder="关于这首曲目的说明"></textarea>
  </label>

  <label>标签 <span class="hint">可留空，多个标签用逗号分隔，自动去重</span>
    <input type="text" name="tags" placeholder="例如：播客, 晨间, 播客">
  </label>

  <label class="check">
    <input type="checkbox" name="save_as_new_version"> 另存为新版本（已有相同来源时仍新增一条独立记录，不覆盖已有资料）
  </label>

  <button type="submit">保存曲目</button>
</form>

<h2>曲目列表</h2>
<div id="tracks"></div>
<p><a href="/api/tracks">查看曲目列表接口</a> · <a href="/health">服务状态</a></p>
</main>

<script>
(function(){
  "use strict";
  var form = document.getElementById("track-form");
  var listBox = document.getElementById("tracks");
  var errBox = document.getElementById("form-error");
  var okBox = document.getElementById("form-ok");
  var conflictBox = document.getElementById("form-conflict");

  function esc(s){
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function clearMsgs(){ errBox.hidden = true; okBox.hidden = true; conflictBox.hidden = true; }

  function field(name, label, value){
    return "<tr><th>" + esc(label) + "</th><td>" + value + "</td></tr>";
  }
  function renderTrack(t){
    var html = "<table>";
    html += field("标识", "", esc(t.id));
    html += field("名称", "", esc(t.title));
    html += field("来源", "", t.source ? esc(t.source) : '<span class="muted">未填写</span>');
    html += field("时长（秒）", "", (t.duration === null || t.duration === undefined) ? '<span class="muted">未填写（未知）</span>' : esc(t.duration));
    var cover = '<span class="muted">未填写</span>';
    if (t.cover) cover = '<a class="cover-link" href="' + esc(t.cover) + '" rel="noopener noreferrer" target="_blank">' + esc(t.cover) + "</a>";
    html += field("封面地址", "", cover);
    html += field("说明", "", t.notes ? '<span class="notes">' + esc(t.notes) + "</span>" : '<span class="muted">未填写</span>');
    var tagsHtml = '<span class="muted">未填写</span>';
    if (t.tags && t.tags.length){
      tagsHtml = '<span class="tags">' + t.tags.map(function(x){ return '<span class="tag">' + esc(x) + "</span>"; }).join("") + "</span>";
    }
    html += field("标签", "", tagsHtml);
    html += "</table>";
    return html;
  }
  function load(){
    return fetch("/api/tracks").then(function(r){ return r.json(); }).then(function(data){
      var tracks = data.tracks || [];
      if (!tracks.length){
        listBox.innerHTML = '<p class="empty">还没有曲目记录。请使用上方表单手动收录第一首曲目。</p>';
        return;
      }
      listBox.innerHTML = tracks.map(function(t){
        return '<div style="margin:.75rem 0;border:1px solid #e5e7eb;border-radius:.75rem;padding:.25rem 1rem">' + renderTrack(t) + "</div>";
      }).join("");
    }).catch(function(){
      listBox.innerHTML = '<p class="empty">曲目列表加载失败，请稍后重试。</p>';
    });
  }

  form.addEventListener("submit", function(e){
    e.preventDefault();
    clearMsgs();
    var fd = new FormData(form);
    var title = (fd.get("title") || "").toString();
    var source = (fd.get("source") || "").toString();
    var durationRaw = (fd.get("duration") || "").toString().trim();
    var cover = (fd.get("cover") || "").toString();
    var notes = (fd.get("notes") || "").toString();
    var tagsRaw = (fd.get("tags") || "").toString();
    var saveAs = fd.get("save_as_new_version") === "on";

    var payload = { title: title, source: source, cover: cover, notes: notes, save_as_new_version: saveAs };
    if (durationRaw !== ""){
      var d = Number(durationRaw);
      payload.duration = d;
    } else {
      payload.duration = null;
    }
    payload.tags = tagsRaw.split(/[,，]/).map(function(x){ return x.trim(); }).filter(function(x){ return x !== ""; });

    fetch("/api/tracks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function(r){
      return r.json().then(function(data){ return { status: r.status, data: data }; });
    }).then(function(res){
      if (res.status === 201){
        okBox.textContent = "已保存曲目：#" + res.data.track.id + " " + res.data.track.title;
        okBox.hidden = false;
        form.reset();
        load();
      } else if (res.status === 409){
        var list = (res.data.tracks || []).map(function(t){ return "#" + t.id + " " + t.title; }).join("、");
        conflictBox.textContent = "该来源已被收录，已有记录：" + list + "。本次填写的资料已保留；勾选「另存为新版本」后再次保存，将新增一条独立记录，不会覆盖已有资料。";
        conflictBox.hidden = false;
        form.querySelector('[name=save_as_new_version]').checked = true;
      } else {
        errBox.textContent = "保存失败：" + (res.data.error || "请检查填写内容");
        errBox.hidden = false;
      }
    }).catch(function(){
      errBox.textContent = "保存失败：网络错误，请稍后重试。";
      errBox.hidden = false;
    });
  });

  load();
})();
</script>
</html>
'''


class ValidationError(Exception):
    """Raised when a submitted track payload is invalid."""


def _reject_constant(_value):
    raise ValueError("invalid JSON constant")


def parse_body(raw):
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValidationError("请求体不是有效的 JSON")


def _require_string(data, field, label):
    value = data.get(field)
    if not isinstance(value, str):
        raise ValidationError(f"{label}必须是字符串")
    return value


def parse_track_payload(data):
    """Validate a decoded JSON payload; return a normalized record dict."""
    if not isinstance(data, dict):
        raise ValidationError("请求体必须是 JSON 对象")

    title = _require_string(data, "title", "名称（title）")
    if not title.strip():
        raise ValidationError("名称（title）必填，去掉首尾空白后不能为空")
    title = title.strip()

    source = _require_string(data, "source", "来源（source）")
    if not source.strip():
        raise ValidationError("来源（source）必填，去掉首尾空白后不能为空")
    source = source.strip()

    duration = data.get("duration")
    if duration is None:
        duration = None
    elif isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise ValidationError("时长（duration）必须是数字")
    elif not math.isfinite(duration) or duration < 0:
        raise ValidationError("时长（duration）必须是有限的非负数")
    else:
        duration = float(duration)

    cover = data.get("cover")
    if cover is None:
        cover = ""
    elif not isinstance(cover, str):
        raise ValidationError("封面地址（cover）必须是字符串")

    notes = data.get("notes")
    if notes is None:
        notes = ""
    elif not isinstance(notes, str):
        raise ValidationError("说明（notes）必须是字符串")

    tags_raw = data.get("tags")
    if tags_raw is None:
        tags = []
    elif not isinstance(tags_raw, list):
        raise ValidationError("标签（tags）必须是字符串数组")
    else:
        tags = []
        seen = set()
        for item in tags_raw:
            if not isinstance(item, str):
                raise ValidationError("标签（tags）数组的每一项都必须是字符串")
            tag = item.strip()
            if tag and tag not in seen:
                seen.add(tag)
                tags.append(tag)

    save_as_new_version = data.get("save_as_new_version", False)
    if not isinstance(save_as_new_version, bool):
        raise ValidationError("save_as_new_version 必须是布尔值")

    return {
        "title": title,
        "source": source,
        "duration": duration,
        "cover": cover,
        "notes": notes,
        "tags": tags,
        "save_as_new_version": save_as_new_version,
    }


def row_to_record(row):
    track_id, title, source, duration, cover, notes, tags_text = row
    try:
        tags = json.loads(tags_text) if tags_text else []
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            tags = []
    except (json.JSONDecodeError, TypeError):
        tags = []
    return {
        "id": track_id,
        "title": title,
        "source": source,
        "duration": duration,
        "cover": cover or "",
        "notes": notes or "",
        "tags": tags,
    }


def main():
    parser = argparse.ArgumentParser(description="SoundShelf - 音频曲目与播放清单")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the HTTP service")
    serve.add_argument("--host", default="127.0.0.1", help="Address to bind (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8080, help="Port to bind; 0 selects an available port")
    serve.add_argument("--data-dir", type=Path, default=Path("data"), help="Directory for the local SQLite database")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(args.data_dir / "sound-shelf.sqlite")
    database.execute(
        "CREATE TABLE IF NOT EXISTS tracks (id INTEGER PRIMARY KEY, title TEXT NOT NULL)"
    )
    existing_columns = {row[1] for row in database.execute("PRAGMA table_info(tracks)")}
    for name, ddl in (
        ("source", "TEXT"),
        ("duration", "REAL"),
        ("cover", "TEXT"),
        ("notes", "TEXT"),
        ("tags", "TEXT"),
    ):
        if name not in existing_columns:
            database.execute(f"ALTER TABLE tracks ADD COLUMN {name} {ddl}")
    database.commit()
    db_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, value, *, html=False):
            payload = value.encode("utf8") if html else json.dumps(value, ensure_ascii=False).encode("utf8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            if status == 405:
                self.send_header("Allow", "GET, POST" if urlsplit(self.path).path == "/api/tracks" else "GET")
            self.end_headers()
            self.wfile.write(payload)

        def create_track(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                self.respond(400, {"error": "缺少或无效的 Content-Length"})
                return
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                data = parse_body(raw)
                payload = parse_track_payload(data)
            except ValidationError as exc:
                self.respond(400, {"error": str(exc)})
                return

            with db_lock:
                if not payload["save_as_new_version"]:
                    conflicts = [
                        {"id": row[0], "title": row[1]}
                        for row in database.execute(
                            "SELECT id, title FROM tracks WHERE source = ? ORDER BY id",
                            (payload["source"],),
                        )
                    ]
                    if conflicts:
                        self.respond(409, {
                            "error": "该来源已存在收录记录，未新增；如需继续请选择另存为新版本",
                            "tracks": conflicts,
                        })
                        return
                cursor = database.execute(
                    "INSERT INTO tracks (title, source, duration, cover, notes, tags) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        payload["title"],
                        payload["source"],
                        payload["duration"],
                        payload["cover"],
                        payload["notes"],
                        json.dumps(payload["tags"], ensure_ascii=False),
                    ),
                )
                database.commit()
                row = database.execute(
                    "SELECT id, title, source, duration, cover, notes, tags FROM tracks WHERE id = ?",
                    (cursor.lastrowid,),
                ).fetchone()
            self.respond(201, {"track": row_to_record(row)})

        def route(self):
            location = urlsplit(self.path).path
            if location not in ("/", "/health", "/api/tracks"):
                self.respond(404, {"error": "not found"})
                return
            if self.command == "GET":
                if location == "/":
                    self.respond(200, PAGE, html=True)
                elif location == "/health":
                    self.respond(200, {"status": "ok", "product": PRODUCT})
                else:
                    records = [
                        row_to_record(row)
                        for row in database.execute(
                            "SELECT id, title, source, duration, cover, notes, tags FROM tracks ORDER BY id"
                        )
                    ]
                    self.respond(200, {RESOURCE: records})
            elif self.command == "POST" and location == "/api/tracks":
                self.create_track()
            else:
                self.respond(405, {"error": "method not allowed"})

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = route

    def stop(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    server = None
    try:
        server = HTTPServer((args.host, args.port), Handler)
        host, port = server.server_address[:2]
        address = f"[{host}]" if ":" in host else host
        print(f"{PRODUCT} listening on http://{address}:{port}", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.server_close()
        database.close()


if __name__ == "__main__":
    main()
