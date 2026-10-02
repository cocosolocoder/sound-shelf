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

# 编辑时允许修改的资料字段，也是 PATCH 请求会识别的全部键。
PATCHABLE_FIELDS = ("title", "source", "duration", "cover_url", "description", "tags")


class PayloadError(Exception):
    """字段校验失败，field 为出错字段名。"""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field
        self.message = message


class TrackNotFoundError(Exception):
    """请求编辑的曲目标识不存在。"""

    def __init__(self, track_id):
        super().__init__(f"曲目不存在：{track_id}")
        self.track_id = track_id


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


def clean_title(value):
    if not isinstance(value, str):
        raise PayloadError("title", "名称必须是字符串")
    value = value.strip()
    if not value:
        raise PayloadError("title", "名称去掉首尾空白后不能为空")
    return value


def clean_source(value):
    if not isinstance(value, str):
        raise PayloadError("source", "来源必须是字符串")
    value = value.strip()
    if not value:
        raise PayloadError("source", "来源去掉首尾空白后不能为空")
    return value


def clean_duration(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PayloadError("duration", "时长必须是数字（秒），留空或 null 表示未知")
    if not math.isfinite(value):
        raise PayloadError("duration", "时长必须是有限的非负数字（秒）")
    if value < 0:
        raise PayloadError("duration", "时长不能为负数（秒）")
    return float(value)


def clean_cover_url(value):
    if not isinstance(value, str):
        raise PayloadError("cover_url", "封面地址必须是字符串")
    return value.strip()


def clean_description(value):
    if not isinstance(value, str):
        raise PayloadError("description", "说明必须是字符串")
    # 保留用户输入原文，包括换行与首尾空白。
    return value


def clean_tags(value):
    if not isinstance(value, list):
        raise PayloadError("tags", "标签必须是字符串数组")
    tags = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            raise PayloadError("tags", "标签中的每一项都必须是字符串")
        tag = item.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags


FIELD_CLEANERS = {
    "title": clean_title,
    "source": clean_source,
    "duration": clean_duration,
    "cover_url": clean_cover_url,
    "description": clean_description,
    "tags": clean_tags,
}


def clean_payload(data):
    """校验并规整一份曲目资料，返回可直接入库的 dict。

    页面表单转换后的字典与外部 JSON 请求共用这套规则。
    任何不合法输入都抛 PayloadError，且不会写入数据。
    """
    if not isinstance(data, dict):
        raise PayloadError(None, "请求体必须是 JSON 对象")

    if data.get("title") is None:
        raise PayloadError("title", "名称为必填项")
    title = clean_title(data["title"])

    if data.get("source") is None:
        raise PayloadError("source", "来源为必填项")
    source = clean_source(data["source"])

    duration = clean_duration(data.get("duration"))
    raw_cover = data.get("cover_url")
    cover_url = clean_cover_url("" if raw_cover is None else raw_cover)
    raw_description = data.get("description")
    description = clean_description("" if raw_description is None else raw_description)
    raw_tags = data.get("tags")
    tags = clean_tags([] if raw_tags is None else raw_tags)

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


def clean_patch(data, current):
    """校验 PATCH 资料字段，与当前记录合并后返回新 dict。

    只处理明确提交的字段，省略的字段沿用当前值；任何字段不合法都抛
    PayloadError，调用方需在全部校验通过后才写库。旧记录（source 为
    None）只有在来源字段被省略时才继续保持缺失状态；显式提交空字符串
    或 null 一律按非法处理（clean_source 返回 400），已有来源的记录
    因此也不可能被清空。
    """
    if not isinstance(data, dict):
        raise PayloadError(None, "请求体必须是 JSON 对象")

    merged = {name: current[name] for name in PATCHABLE_FIELDS}
    for name in PATCHABLE_FIELDS:
        if name in data:
            merged[name] = FIELD_CLEANERS[name](data[name])

    return merged


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


def update_track(database, track_id, data):
    """校验并更新一条已有曲目。

    返回 (record, conflicts)：
    - 成功：(更新后的完整记录, None)
    - 来源与其他记录冲突：(None, conflicts)，记录保持原样
    曲目标识不存在时抛 TrackNotFoundError；字段不合法时抛 PayloadError。
    两种失败都发生在写库之前，记录保持原样。
    """
    current = get_track(database, track_id)
    if current is None:
        raise TrackNotFoundError(track_id)

    merged = clean_patch(data, current)

    # 只有来源确实改成另一段文字时才重新判重；来源未改变时（包括同一
    # 来源已有多个版本、以及旧记录仍缺来源）允许修改本条其他资料。
    if merged["source"] is not None and merged["source"] != current["source"]:
        others = [
            item
            for item in find_conflicts(database, merged["source"])
            if item["id"] != track_id
        ]
        if others:
            return None, others

    database.execute(
        """
        UPDATE tracks
        SET title = :title, source = :source, duration = :duration,
            cover_url = :cover_url, description = :description, tags = :tags
        WHERE id = :id
        """,
        {
            **merged,
            "id": track_id,
            "tags": json.dumps(merged["tags"], ensure_ascii=False),
        },
    )
    database.commit()
    return get_track(database, track_id), None


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
    if row is None:
        return None
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


def format_duration_for_input(value):
    """表单时长输入框的字面值：未知或旧记录缺值时为空串。"""
    if value is None:
        return ""
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def format_duration(value):
    if value is None:
        return None
    number = float(value)
    text = str(int(number)) if number.is_integer() else str(number)
    return f"{text} 秒"


FORM_FIELDS = ("title", "source", "duration", "cover_url", "description", "tags")


def parse_duration_field(text):
    """把表单中的时长文字转成数字；留空为 None，非法时抛 PayloadError。"""
    raw = text.strip()
    if raw == "":
        return None
    try:
        number = float(raw)
    except ValueError:
        raise PayloadError(
            "duration", "时长必须是有限的非负数字（秒），留空表示未知"
        )
    return clean_duration(number)


def tags_text_to_items(text):
    # 标签按中英文逗号和顿号分隔，后续规则与接口一致。
    return [part for part in re.split(r"[,，、]+", text)]


STYLES = """
body{font-family:system-ui,sans-serif;max-width:52rem;margin:2.5rem auto;padding:0 1rem;line-height:1.7;color:#1f2933}
a{color:#175b9c}
h2{margin-top:2.5rem;border-bottom:1px solid #d9e2ec;padding-bottom:.3rem}
.banner{padding:.7rem 1rem;border-radius:6px;margin:1rem 0}
.banner.success{background:#e6f6ec;border:1px solid #8fd3a8}
.banner.error{background:#fdecea;border:1px solid #f2a39a}
.banner.conflict{background:#fff7e6;border:1px solid #f0c36d}
.conflict-list{margin:.4rem 0}
form.track-form{border:1px solid #d9e2ec;border-radius:8px;padding:1rem 1.25rem;background:#f8fafc}
form.track-form label{display:block;font-weight:600;margin-top:.8rem}
form.track-form .hint{font-weight:400;color:#627d98;font-size:.9em}
form.track-form input[type=text],form.track-form textarea{width:100%;box-sizing:border-box;padding:.45rem .6rem;border:1px solid #bcccdc;border-radius:4px;font:inherit}
form.track-form textarea{min-height:5.5rem;resize:vertical}
.field-error{color:#b3261e;margin:.25rem 0 0;font-size:.92em}
form.track-form button{margin-top:1.1rem;padding:.5rem 1.2rem;font:inherit;border-radius:5px;border:1px solid #14507a;background:#1769aa;color:#fff;cursor:pointer}
.checkbox-line{margin-top:1rem}
.checkbox-line label{display:inline;font-weight:400}
ol.tracks{list-style:none;padding:0;display:flex;flex-direction:column;gap:1rem}
ol.tracks li{border:1px solid #d9e2ec;border-radius:8px;padding:.8rem 1.1rem;background:#fff}
ol.tracks li.highlight{border-color:#1769aa;box-shadow:0 0 0 2px rgba(23,105,170,.18)}
.track-id{display:inline-block;min-width:2.6em;color:#627d98;font-variant-numeric:tabular-nums}
.track-title{font-size:1.12em;font-weight:700;margin:0 0 .4rem}
.track-title a.edit-link{font-size:.7em;font-weight:400;margin-left:.6rem;white-space:nowrap}
.track-meta{display:grid;grid-template-columns:5.5rem 1fr;gap:.15rem .8rem;margin:0}
.track-meta dt{color:#627d98}
.track-meta dd{margin:0;word-break:break-all}
.notes{white-space:pre-wrap;word-break:normal}
.unfilled{color:#829ab1}
.tag{display:inline-block;background:#e4e7eb;border-radius:999px;padding:.05rem .7rem;margin:.1rem .25rem .1rem 0;font-size:.88em}
.btn-cancel{display:inline-block;margin-top:1.1rem;margin-left:.6rem;padding:.5rem 1.2rem;font:inherit;border-radius:5px;border:1px solid #1769aa;background:#fff;color:#1769aa;text-decoration:none}
.back-link{margin:0}
"""


def render_shell(title, body):
    return f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>{STYLES}</style>
<main>
{body}
</main>
</html>"""


def render_conflict_banner(conflicts, *, intro, footer):
    items = "".join(
        f'<li><span class="track-id">#{item["id"]}</span> {esc(item["title"])}</li>'
        for item in conflicts
    )
    return (
        '<div class="banner conflict" role="alert">'
        f"<p>{intro}</p>"
        f'<ul class="conflict-list">{items}</ul>'
        f"<p>{footer}</p>"
        "</div>"
    )


def render_page(tracks, *, form=None, error=None, error_field=None,
                conflicts=None, highlight=None, updated=None):
    form = form or {}

    def value(name):
        return esc(form.get(name, ""))

    error_html = ""
    if error:
        error_html = f'<p class="banner error" role="alert">{esc(error)}</p>'

    conflict_html = ""
    if conflicts:
        conflict_html = render_conflict_banner(
            conflicts,
            intro=(
                "<strong>该来源已经收录过曲目，默认不会重复新增。</strong>"
                "已有记录如下，请辨认是否是同一首："
            ),
            footer=(
                "如果这是同一来源的另一个版本（例如不同码率或重新上传），"
                "请勾选下方“另存为新版本”后再次保存，已有记录不会被修改。"
            ),
        )

    checked = "checked" if form.get("save_as_new_version") else ""
    inline_error = (
        lambda name: f'<p class="field-error">{esc(error)}</p>'
        if error_field == name else ""
    )

    if tracks:
        items = "".join(render_track(record, highlight or updated) for record in tracks)
        listing = f'<ol class="tracks">{items}</ol>'
    else:
        listing = (
            '<p class="empty">还没有曲目记录。'
            "使用下方表单手动收录第一首曲目吧。</p>"
        )

    notice = ""
    if updated is not None:
        notice = (
            f'<p class="banner success">保存成功，曲目 '
            f'<strong>#{updated}</strong> 的资料已更新，'
            "原标识保持不变，下方列表显示的就是最新内容。</p>"
        )
    elif highlight is not None:
        notice = (
            f'<p class="banner success">收录成功，曲目 <strong>#{highlight}</strong> '
            "已加入下方列表。</p>"
        )

    body = f"""
<h1>{PRODUCT}</h1>
<p>音频曲目与播放清单</p>
{notice}
<h2 id="add">手动收录曲目</h2>
{conflict_html}
{error_html}
<form class="track-form" method="post" action="/" novalidate>
  <label for="f-title">名称 <span class="hint">（必填）</span></label>
  <input type="text" id="f-title" name="title" value="{value("title")}">
  {inline_error("title")}
  <label for="f-source">来源 <span class="hint">（必填，网址或本地文件路径，按去掉首尾空白后的文字保存，不检查能否播放）</span></label>
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
"""
    return render_shell(f"{PRODUCT} · 音频曲目与播放清单", body)


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
<p class="track-title"><span class="track-id">#{record["id"]}</span>{esc(record["title"])}<a class="edit-link" href="/tracks/{record["id"]}/edit">编辑</a></p>
<dl class="track-meta">
<dt>来源</dt><dd>{source_cell}</dd>
<dt>时长</dt><dd>{duration_cell}</dd>
<dt>封面地址</dt><dd>{cover_cell}</dd>
<dt>标签</dt><dd>{tags_cell}</dd>
<dt>说明</dt><dd class="notes">{notes_cell}</dd>
</dl>
</li>"""


def render_missing_track_page():
    body = """
<h1>SoundShelf</h1>
<p class="banner error" role="alert">曲目不存在：没有找到这条曲目记录，无法编辑。</p>
<p><a href="/">返回曲目列表</a></p>
"""
    return render_shell(f"曲目不存在 · {PRODUCT}", body)


def form_view_from_record(record):
    """用当前记录预填编辑表单（全部为字符串，供表单回显）。"""
    return {
        "title": record["title"],
        "source": "" if record["source"] is None else record["source"],
        "duration": format_duration_for_input(record["duration"]),
        "cover_url": record["cover_url"],
        "description": record["description"],
        "tags": ", ".join(record["tags"]),
    }


def render_edit_page(record, *, form=None, error=None, error_field=None,
                     conflicts=None):
    form = form if form is not None else form_view_from_record(record)

    def value(name):
        return esc(form.get(name, ""))

    error_html = ""
    if error:
        error_html = f'<p class="banner error" role="alert">{esc(error)}</p>'

    conflict_html = ""
    if conflicts:
        conflict_html = render_conflict_banner(
            conflicts,
            intro=(
                "<strong>修改后的来源已被其他曲目使用，本次保存没有生效。</strong>"
                "冲突记录如下："
            ),
            footer=(
                "不能覆盖对方、合并记录或自动另存为新版本。请修改来源后重试；"
                "如果这确实是同一来源的另一个版本，请取消编辑，回到首页使用"
                "收录功能并勾选“另存为新版本”。"
            ),
        )

    legacy_hint = ""
    if record["source"] is None:
        legacy_hint = (
            '<p class="banner conflict">这条旧记录目前还没有来源。'
            "可以只修改名称等其他资料，来源留空会继续保持缺失状态、"
            "不参加来源重复判断；一旦填写了来源并保存，以后就不能再清空。</p>"
        )

    inline_error = (
        lambda name: f'<p class="field-error">{esc(error)}</p>'
        if error_field == name else ""
    )

    body = f"""
<p class="back-link"><a href="/">← 返回曲目列表</a></p>
<h1>编辑曲目 <span class="track-id">#{record["id"]}</span></h1>
<p class="unfilled">保存后标识 #{record["id"]} 保持不变，只修改这一条记录；其他曲目以及同来源的其他版本不受影响。</p>
{legacy_hint}
{conflict_html}
{error_html}
<form class="track-form" method="post" action="/tracks/{record["id"]}/edit" novalidate>
  <label for="f-title">名称 <span class="hint">（必填，去掉首尾空白后不能为空）</span></label>
  <input type="text" id="f-title" name="title" value="{value("title")}">
  {inline_error("title")}
  <label for="f-source">来源 <span class="hint">（旧记录可继续留空；已有来源的记录不能清空；按去掉首尾空白后的文字保存）</span></label>
  <input type="text" id="f-source" name="source" value="{value("source")}">
  {inline_error("source")}
  <label for="f-duration">时长 <span class="hint">（秒，留空表示未知；允许 0 和小数）</span></label>
  <input type="text" id="f-duration" name="duration" inputmode="decimal" value="{value("duration")}">
  {inline_error("duration")}
  <label for="f-cover-url">封面地址 <span class="hint">（可留空，不会检查远端文件）</span></label>
  <input type="text" id="f-cover-url" name="cover_url" value="{value("cover_url")}">
  {inline_error("cover_url")}
  <label for="f-description">说明 <span class="hint">（可留空，保留换行）</span></label>
  <textarea id="f-description" name="description">{esc(form.get("description", ""))}</textarea>
  {inline_error("description")}
  <label for="f-tags">标签 <span class="hint">（可留空，多个标签用逗号分隔；保存时整体替换并自动去重）</span></label>
  <input type="text" id="f-tags" name="tags" value="{value("tags")}">
  {inline_error("tags")}
  <button type="submit">保存修改</button>
  <a class="btn-cancel" href="/">取消</a>
</form>
"""
    return render_shell(f"编辑曲目 #{record['id']} · {PRODUCT}", body)


def form_to_payload(form):
    """把收录表单转成 clean_payload 接受的完整资料字典。"""
    def one(name):
        return form.get(name, [""])[0]

    return {
        "title": one("title"),
        "source": one("source"),
        "duration": parse_duration_field(one("duration")),
        "cover_url": one("cover_url"),
        "description": one("description"),
        "tags": tags_text_to_items(one("tags")),
        "save_as_new_version": one("save_as_new_version") in ("1", "on", "true", "yes"),
    }


def edit_form_to_patch(record, form):
    """把编辑表单转成 PATCH 资料字典。

    表单里每个字段都会出现，但旧记录的来源留空表示“继续缺失”，对应
    PATCH 语义里的“省略该字段”，因此此时不放入 source 键。
    """
    def one(name):
        return form.get(name, [""])[0]

    patch = {
        "title": one("title"),
        "duration": parse_duration_field(one("duration")),
        "cover_url": one("cover_url"),
        "description": one("description"),
        "tags": tags_text_to_items(one("tags")),
    }
    source_text = one("source")
    if record["source"] is not None or source_text.strip() != "":
        patch["source"] = source_text
    return patch


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
            updated = None
            raw_updated = query.get("updated", [""])[0]
            if raw_updated.isdigit():
                updated = int(raw_updated)
            self.respond(
                200,
                render_page(
                    list_tracks(database), highlight=highlight, updated=updated
                ),
                html=True,
            )

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

        def handle_edit_get(self, track_id):
            record = get_track(database, track_id)
            if record is None:
                self.respond(404, render_missing_track_page(), html=True)
                return
            self.respond(200, render_edit_page(record), html=True)

        def handle_edit_post(self, track_id):
            record = get_track(database, track_id)
            if record is None:
                self.respond(404, render_missing_track_page(), html=True)
                return

            raw = self.read_body().decode("utf-8", errors="replace")
            form = parse_qs(raw, keep_blank_values=True)
            # 回显用：保留本次输入的原始文字。
            form_view = {name: form.get(name, [""])[0] for name in FORM_FIELDS}

            def fail(status, message, *, field=None, conflicts=None):
                self.respond(
                    status,
                    render_edit_page(
                        record,
                        form=form_view,
                        error=message,
                        error_field=field,
                        conflicts=conflicts,
                    ),
                    html=True,
                )

            try:
                patch = edit_form_to_patch(record, form)
                updated, conflicts = update_track(database, track_id, patch)
            except PayloadError as exc:
                fail(
                    400,
                    f"保存失败：{FIELD_LABELS.get(exc.field, '输入')}有误——{exc.message}",
                    field=exc.field,
                )
                return
            except TrackNotFoundError:
                self.respond(404, render_missing_track_page(), html=True)
                return
            if conflicts is not None:
                fail(
                    409,
                    "保存失败：修改后的来源已被其他曲目使用，请查看下方冲突记录。",
                    field="source",
                    conflicts=conflicts,
                )
                return
            self.respond(
                303,
                "",
                html=True,
                extra_headers=[("Location", f"/?updated={updated['id']}")],
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

        def handle_api_patch(self, track_id):
            raw = self.read_body()
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.respond(400, {"error": "请求体不是有效的 JSON"})
                return
            try:
                record, conflicts = update_track(database, track_id, data)
            except PayloadError as exc:
                label = FIELD_LABELS.get(exc.field)
                message = f"{label}有误：{exc.message}" if label else exc.message
                self.respond(400, {"error": message, "field": exc.field})
                return
            except TrackNotFoundError:
                self.respond(
                    404,
                    {
                        "error": f"曲目不存在：没有标识为 {track_id} 的曲目",
                        "field": None,
                    },
                )
                return
            if conflicts is not None:
                self.respond(
                    409,
                    {
                        "error": "修改后的来源已被其他曲目使用；不能覆盖或合并记录，如确需另存为新版本，请改用收录接口",
                        "field": "source",
                        "existing": conflicts,
                    },
                )
                return
            self.respond(200, record)

        def route(self):
            location = urlsplit(self.path)
            path = location.path

            item_match = re.fullmatch(r"/api/tracks/(\d+)", path)
            edit_match = re.fullmatch(r"/tracks/(\d+)/edit", path)

            if item_match:
                if self.command != "PATCH":
                    self.respond(
                        405,
                        {"error": "method not allowed"},
                        extra_headers=[("Allow", "PATCH")],
                    )
                    return
                self.handle_api_patch(int(item_match.group(1)))
                return

            if edit_match:
                if self.command not in ("GET", "POST"):
                    self.respond(
                        405,
                        {"error": "method not allowed"},
                        extra_headers=[("Allow", "GET, POST")],
                    )
                    return
                if self.command == "GET":
                    self.handle_edit_get(int(edit_match.group(1)))
                else:
                    self.handle_edit_post(int(edit_match.group(1)))
                return

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
