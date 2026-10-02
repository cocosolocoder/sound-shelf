#!/usr/bin/env python3
"""SoundShelf HTTP service."""
import argparse
import html
import json
import math
import re
import signal
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

PRODUCT = "SoundShelf"
RESOURCE = "tracks"

FIELD_LABELS = {
    "title": "名称",
    "source": "来源",
    "duration": "时长",
    "cover_url": "封面地址",
    "description": "说明",
    "tags": "标签",
    "save_as_new_version": "另存为新版本",
}

TRACK_COLUMNS = "id, title, source, duration, cover_url, description, tags"


class PayloadError(Exception):
    """字段校验失败，field 为出错字段名。"""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field
        self.message = message


def connect_database(path: Path) -> sqlite3.Connection:
    database = sqlite3.connect(path)
    database.execute(
        "CREATE TABLE IF NOT EXISTS tracks (id INTEGER PRIMARY KEY, title TEXT NOT NULL)"
    )
    present = {row[1] for row in database.execute("PRAGMA table_info(tracks)")}
    migrations = {
        "source": "TEXT",
        "duration": "REAL",
        "cover_url": "TEXT",
        "description": "TEXT",
        "tags": "TEXT",
    }
    for name, column_type in migrations.items():
        if name not in present:
            database.execute(f"ALTER TABLE tracks ADD COLUMN {name} {column_type}")
    database.commit()
    return database


def clean_payload(data):
    """校验并规整一份曲目资料，返回可直接入库的 dict。

    页面表单转换后的字典与外部 JSON 请求共用这套规则。
    任何不合法输入都抛 PayloadError，且不会写入数据。
    """
    if not isinstance(data, dict):
        raise PayloadError(None, "请求体必须是 JSON 对象")

    title = data.get("title")
    if title is None:
        raise PayloadError("title", "名称为必填项")
    if not isinstance(title, str):
        raise PayloadError("title", "名称必须是字符串")
    title = title.strip()
    if not title:
        raise PayloadError("title", "名称去掉首尾空白后不能为空")

    source = data.get("source")
    if source is None:
        raise PayloadError("source", "来源为必填项")
    if not isinstance(source, str):
        raise PayloadError("source", "来源必须是字符串")
    source = source.strip()
    if not source:
        raise PayloadError("source", "来源去掉首尾空白后不能为空")

    raw_duration = data.get("duration")
    if raw_duration is None:
        duration = None
    else:
        if isinstance(raw_duration, bool) or not isinstance(raw_duration, (int, float)):
            raise PayloadError("duration", "时长必须是数字（秒），留空表示未知")
        if not math.isfinite(raw_duration):
            raise PayloadError("duration", "时长必须是有限的非负数字（秒）")
        if raw_duration < 0:
            raise PayloadError("duration", "时长不能为负数（秒）")
        duration = float(raw_duration)

    cover_url = data.get("cover_url")
    if cover_url is None:
        cover_url = ""
    elif not isinstance(cover_url, str):
        raise PayloadError("cover_url", "封面地址必须是字符串")
    else:
        cover_url = cover_url.strip()

    description = data.get("description")
    if description is None:
        description = ""
    elif not isinstance(description, str):
        raise PayloadError("description", "说明必须是字符串")
    # 保留用户输入原文，包括换行与首尾空白。

    raw_tags = data.get("tags")
    if raw_tags is None:
        raw_tags = []
    if not isinstance(raw_tags, list):
        raise PayloadError("tags", "标签必须是字符串数组")
    tags = []
    seen = set()
    for item in raw_tags:
        if not isinstance(item, str):
            raise PayloadError("tags", "标签中的每一项都必须是字符串")
        tag = item.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)

    force = data.get("save_as_new_version", False)
    if not isinstance(force, bool):
        raise PayloadError(
            "save_as_new_version", "save_as_new_version 必须是布尔值"
        )

    return {
        "title": title,
        "source": source,
        "duration": duration,
        "cover_url": cover_url,
        "description": description,
        "tags": tags,
        "save_as_new_version": force,
    }


def create_track(database, data):
    """校验并写入一条曲目。返回 (record, conflicts)。

    成功时 conflicts 为 None；来源重复且未明确另存时 record 为 None，
    conflicts 为该来源已有记录（按 id 升序）。
    """
    clean = clean_payload(data)
    force = clean.pop("save_as_new_version")

    conflicts = find_conflicts(database, clean["source"])
    if conflicts and not force:
        return None, conflicts

    cursor = database.execute(
        """
        INSERT INTO tracks (title, source, duration, cover_url, description, tags)
        VALUES (:title, :source, :duration, :cover_url, :description, :tags)
        """,
        {**clean, "tags": json.dumps(clean["tags"], ensure_ascii=False)},
    )
    database.commit()
    return get_track(database, cursor.lastrowid), None


def find_conflicts(database, source):
    rows = database.execute(
        "SELECT id, title FROM tracks WHERE source = ? ORDER BY id ASC", (source,)
    ).fetchall()
    return [{"id": row[0], "title": row[1]} for row in rows]


def get_track(database, track_id):
    row = database.execute(
        f"SELECT {TRACK_COLUMNS} FROM tracks WHERE id = ?", (track_id,)
    ).fetchone()
    return record_from_row(row)


def list_tracks(database):
    rows = database.execute(
        f"SELECT {TRACK_COLUMNS} FROM tracks ORDER BY id ASC"
    ).fetchall()
    return [record_from_row(row) for row in rows]


def record_from_row(row):
    duration = row[3]
    if duration is not None:
        duration = float(duration)
        if duration.is_integer():
            duration = int(duration)
    try:
        tags = json.loads(row[6]) if row[6] else []
    except (ValueError, TypeError):
        tags = []
    return {
        "id": row[0],
        "title": row[1],
        # 旧记录没有来源，输出 null；它也永远不会与任何来源判重。
        "source": row[2],
        "duration": duration,
        "cover_url": row[4] if row[4] is not None else "",
        "description": row[5] if row[5] is not None else "",
        "tags": tags,
    }


# ---------------------------------------------------------------------------
# 首页


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def format_duration(value):
    if value is None:
        return None
    number = float(value)
    text = str(int(number)) if number.is_integer() else str(number)
    return f"{text} 秒"


FORM_FIELDS = ("title", "source", "duration", "cover_url", "description", "tags")


def render_page(tracks, *, form=None, error=None, error_field=None,
                conflicts=None, highlight=None):
    form = form or {}

    def value(name):
        return esc(form.get(name, ""))

    error_html = ""
    if error:
        error_html = f'<p class="banner error" role="alert">{esc(error)}</p>'

    conflict_html = ""
    if conflicts:
        items = "".join(
            f'<li><span class="track-id">#{item["id"]}</span> {esc(item["title"])}</li>'
            for item in conflicts
        )
        conflict_html = (
            '<div class="banner conflict" role="alert">'
            "<p><strong>该来源已经收录过曲目，默认不会重复新增。</strong>"
            "已有记录如下，请辨认是否是同一首：</p>"
            f'<ul class="conflict-list">{items}</ul>'
            "<p>如果这是同一来源的另一个版本（例如不同码率或重新上传），"
            "请勾选下方“另存为新版本”后再次保存，已有记录不会被修改。</p>"
            "</div>"
        )

    checked = "checked" if form.get("save_as_new_version") else ""
    inline_error = (
        lambda name: f'<p class="field-error">{esc(error)}</p>'
        if error_field == name else ""
    )

    if tracks:
        items = "".join(render_track(record, highlight) for record in tracks)
        listing = f'<ol class="tracks">{items}</ol>'
    else:
        listing = (
            '<p class="empty">还没有曲目记录。'
            "使用下方表单手动收录第一首曲目吧。</p>"
        )

    highlight_notice = ""
    if highlight is not None:
        highlight_notice = (
            f'<p class="banner success">收录成功，曲目 <strong>#{highlight}</strong> '
            "已加入下方列表。</p>"
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{PRODUCT} · 音频曲目与播放清单</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:52rem;margin:2.5rem auto;padding:0 1rem;line-height:1.7;color:#1f2933}}
a{{color:#175b9c}}
h2{{margin-top:2.5rem;border-bottom:1px solid #d9e2ec;padding-bottom:.3rem}}
.banner{{padding:.7rem 1rem;border-radius:6px;margin:1rem 0}}
.banner.success{{background:#e6f6ec;border:1px solid #8fd3a8}}
.banner.error{{background:#fdecea;border:1px solid #f2a39a}}
.banner.conflict{{background:#fff7e6;border:1px solid #f0c36d}}
.conflict-list{{margin:.4rem 0}}
form.track-form{{border:1px solid #d9e2ec;border-radius:8px;padding:1rem 1.25rem;background:#f8fafc}}
form.track-form label{{display:block;font-weight:600;margin-top:.8rem}}
form.track-form .hint{{font-weight:400;color:#627d98;font-size:.9em}}
form.track-form input[type=text],form.track-form textarea{{width:100%;box-sizing:border-box;padding:.45rem .6rem;border:1px solid #bcccdc;border-radius:4px;font:inherit}}
form.track-form textarea{{min-height:5.5rem;resize:vertical}}
.field-error{{color:#b3261e;margin:.25rem 0 0;font-size:.92em}}
form.track-form button{{margin-top:1.1rem;padding:.5rem 1.2rem;font:inherit;border-radius:5px;border:1px solid #14507a;background:#1769aa;color:#fff;cursor:pointer}}
.checkbox-line{{margin-top:1rem}}
.checkbox-line label{{display:inline;font-weight:400}}
ol.tracks{{list-style:none;padding:0;display:flex;flex-direction:column;gap:1rem}}
ol.tracks li{{border:1px solid #d9e2ec;border-radius:8px;padding:.8rem 1.1rem;background:#fff}}
ol.tracks li.highlight{{border-color:#1769aa;box-shadow:0 0 0 2px rgba(23,105,170,.18)}}
.track-id{{display:inline-block;min-width:2.6em;color:#627d98;font-variant-numeric:tabular-nums}}
.track-title{{font-size:1.12em;font-weight:700;margin:0 0 .4rem}}
.track-meta{{display:grid;grid-template-columns:5.5rem 1fr;gap:.15rem .8rem;margin:0}}
.track-meta dt{{color:#627d98}}
.track-meta dd{{margin:0;word-break:break-all}}
.notes{{white-space:pre-wrap;word-break:normal}}
.unfilled{{color:#829ab1}}
.tag{{display:inline-block;background:#e4e7eb;border-radius:999px;padding:.05rem .7rem;margin:.1rem .25rem .1rem 0;font-size:.88em}}
</style>
<main>
<h1>{PRODUCT}</h1>
<p>音频曲目与播放清单</p>
{highlight_notice}
<h2 id="add">手动收录曲目</h2>
{conflict_html}
{error_html}
<form class="track-form" method="post" action="/" novalidate>
  <label for="f-title">名称 <span class="hint">（必填）</span></label>
  <input type="text" id="f-title" name="title" value="{value("title")}">
  {inline_error("title")}
  <label for="f-source">来源 <span class="hint">（必填，网址或本地文件路径，按文字原样保存，不检查能否播放）</span></label>
  <input type="text" id="f-source" name="source" value="{value("source")}">
  {inline_error("source")}
  <label for="f-duration">时长 <span class="hint">（秒，可留空表示未知；允许 0 和小数）</span></label>
  <input type="text" id="f-duration" name="duration" inputmode="decimal" value="{value("duration")}">
  {inline_error("duration")}
  <label for="f-cover-url">封面地址 <span class="hint">（可留空，不会检查远端文件）</span></label>
  <input type="text" id="f-cover-url" name="cover_url" value="{value("cover_url")}">
  {inline_error("cover_url")}
  <label for="f-description">说明 <span class="hint">（可留空，保留换行）</span></label>
  <textarea id="f-description" name="description">{esc(form.get("description", ""))}</textarea>
  {inline_error("description")}
  <label for="f-tags">标签 <span class="hint">（可留空，多个标签用逗号分隔；自动去重）</span></label>
  <input type="text" id="f-tags" name="tags" value="{value("tags")}">
  {inline_error("tags")}
  <div class="checkbox-line">
    <input type="checkbox" id="f-force" name="save_as_new_version" value="1" {checked}>
    <label for="f-force">即使该来源已存在，仍将本次填写<strong>另存为新版本</strong></label>
  </div>
  {inline_error("save_as_new_version")}
  <button type="submit">保存曲目</button>
</form>
<h2>曲目列表</h2>
{listing}
<p><a href="/api/tracks">查看曲目列表接口</a> · <a href="/health">服务状态</a></p>
</main>
</html>"""


def render_track(record, highlight=None):
    legacy = record["source"] is None
    highlighted = " highlight" if record["id"] == highlight else ""

    def unfilled(text="未填写"):
        return f'<span class="unfilled">{text}</span>'

    if legacy:
        source_cell = unfilled()
        duration_cell = unfilled()
        cover_cell = unfilled()
        notes_cell = unfilled()
        tags_cell = unfilled("无")
    else:
        source_cell = esc(record["source"])
        if record["duration"] is None:
            duration_cell = unfilled("未知")
        else:
            duration_cell = esc(format_duration(record["duration"]))
        cover_cell = esc(record["cover_url"]) if record["cover_url"] else unfilled()
        notes_cell = esc(record["description"])
        if record["tags"]:
            tags_cell = "".join(
                f'<span class="tag">{esc(tag)}</span>' for tag in record["tags"]
            )
        else:
            tags_cell = unfilled("无")

    return f"""<li id="track-{record["id"]}"{highlighted}>
<p class="track-title"><span class="track-id">#{record["id"]}</span>{esc(record["title"])}</p>
<dl class="track-meta">
<dt>来源</dt><dd>{source_cell}</dd>
<dt>时长</dt><dd>{duration_cell}</dd>
<dt>封面地址</dt><dd>{cover_cell}</dd>
<dt>标签</dt><dd>{tags_cell}</dd>
<dt>说明</dt><dd class="notes">{notes_cell}</dd>
</dl>
</li>"""


render_track.highlight = None


def form_to_payload(form):
    """把 application/x-www-form-urlencoded 表单转成校验器接受的字典。"""
    def one(name):
        return form.get(name, [""])[0]

    raw_duration = one("duration").strip()
    if raw_duration == "":
        duration = None
    else:
        try:
            duration = float(raw_duration)
        except ValueError:
            raise PayloadError(
                "duration", "时长必须是有限的非负数字（秒），留空表示未知"
            )

    payload = {
        "title": one("title"),
        "source": one("source"),
        "duration": duration,
        "cover_url": one("cover_url"),
        "description": one("description"),
        # 标签按中英文逗号和顿号分隔，后续规则与接口一致。
        "tags": [part for part in re.split(r"[,，、]+", one("tags"))],
        "save_as_new_version": one("save_as_new_version") in ("1", "on", "true", "yes"),
    }
    return payload


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
    database = connect_database(args.data_dir / "sound-shelf.sqlite")

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, value, *, html=False, extra_headers=None):
            payload = value.encode("utf8") if html else json.dumps(value, ensure_ascii=False).encode("utf8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            if extra_headers:
                for name, header_value in extra_headers:
                    self.send_header(name, header_value)
            self.end_headers()
            self.wfile.write(payload)

        def read_body(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            return self.rfile.read(max(length, 0))

        def error_page(self, status, message, form, *, field=None, conflicts=None):
            page = render_page(
                list_tracks(database),
                form=form,
                error=message,
                error_field=field,
                conflicts=conflicts,
            )
            self.respond(status, page, html=True)

        def handle_page_get(self, query):
            highlight = None
            raw_highlight = query.get("highlight", [""])[0]
            if raw_highlight.isdigit():
                highlight = int(raw_highlight)
            self.respond(200, render_page(list_tracks(database), highlight=highlight), html=True)

        def handle_page_post(self):
            raw = self.read_body().decode("utf-8", errors="replace")
            form = parse_qs(raw, keep_blank_values=True)
            form_view = {name: form.get(name, [""])[0] for name in FORM_FIELDS}
            form_view["save_as_new_version"] = (
                form.get("save_as_new_version", [""])[0] in ("1", "on", "true", "yes")
            )
            try:
                record, conflicts = create_track(database, form_to_payload(form))
            except PayloadError as exc:
                self.error_page(
                    400,
                    f"保存失败：{FIELD_LABELS.get(exc.field, '输入')}有误——{exc.message}",
                    form_view,
                    field=exc.field,
                )
                return
            if conflicts is not None:
                self.error_page(
                    409,
                    "保存失败：该来源已有收录记录，需要明确选择后才能另存新版本。",
                    form_view,
                    field="source",
                    conflicts=conflicts,
                )
                return
            self.respond(
                303,
                "",
                html=True,
                extra_headers=[("Location", f"/?highlight={record['id']}")],
            )

        def handle_api_get(self):
            self.respond(200, {RESOURCE: list_tracks(database)})

        def handle_api_post(self):
            raw = self.read_body()
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.respond(400, {"error": "请求体不是有效的 JSON"})
                return
            try:
                record, conflicts = create_track(database, data)
            except PayloadError as exc:
                label = FIELD_LABELS.get(exc.field)
                message = f"{label}有误：{exc.message}" if label else exc.message
                self.respond(400, {"error": message, "field": exc.field})
                return
            if conflicts is not None:
                self.respond(
                    409,
                    {
                        "error": "该来源已存在曲目记录；如确需另存为新版本，请将 save_as_new_version 设为 true 后重试",
                        "field": "source",
                        "existing": conflicts,
                    },
                )
                return
            self.respond(201, record)

        def route(self):
            location = urlsplit(self.path)
            path = location.path
            if path not in ("/", "/health", "/api/tracks"):
                self.respond(404, {"error": "not found"})
                return
            if path in ("/", "/api/tracks"):
                allowed = ("GET", "POST")
            else:
                allowed = ("GET",)
            if self.command not in allowed:
                self.respond(
                    405,
                    {"error": "method not allowed"},
                    extra_headers=[("Allow", ", ".join(allowed))],
                )
                return
            if path == "/health":
                self.respond(200, {"status": "ok", "product": PRODUCT})
            elif path == "/":
                if self.command == "GET":
                    self.handle_page_get(parse_qs(location.query))
                else:
                    self.handle_page_post()
            elif self.command == "GET":
                self.handle_api_get()
            else:
                self.handle_api_post()

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = route

        def log_message(self, fmt, *args):  # quieter default access log
            pass

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
