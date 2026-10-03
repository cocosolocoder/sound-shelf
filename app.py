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


def find_conflicts(database, source, exclude_id=None):
    if exclude_id is not None:
        rows = database.execute(
            "SELECT id, title FROM tracks WHERE source = ? AND id != ? ORDER BY id ASC",
            (source, exclude_id),
        ).fetchall()
    else:
        rows = database.execute(
            "SELECT id, title FROM tracks WHERE source = ? ORDER BY id ASC", (source,)
        ).fetchall()
    return [{"id": row[0], "title": row[1]} for row in rows]


def clean_patch_payload(data):
    """校验并规整 PATCH 请求中明确提交的字段，返回只含这些字段的 dict。

    未提交的字段由调用方合并旧值；任何不合法输入都抛 PayloadError，
    且不会写入数据。
    """
    if not isinstance(data, dict):
        raise PayloadError(None, "请求体必须是 JSON 对象")

    clean = {}

    if "title" in data:
        title = data["title"]
        if not isinstance(title, str):
            raise PayloadError("title", "名称必须是字符串")
        title = title.strip()
        if not title:
            raise PayloadError("title", "名称去掉首尾空白后不能为空")
        clean["title"] = title

    if "source" in data:
        source = data["source"]
        if source is None:
            raise PayloadError("source", "来源不能清空；如不再收录该来源，请取消编辑")
        if not isinstance(source, str):
            raise PayloadError("source", "来源必须是字符串")
        source = source.strip()
        if not source:
            raise PayloadError("source", "来源不能清空；如不再收录该来源，请取消编辑")
        clean["source"] = source

    if "duration" in data:
        raw_duration = data["duration"]
        if raw_duration is None:
            duration = None
        else:
            if isinstance(raw_duration, bool) or not isinstance(raw_duration, (int, float)):
                raise PayloadError("duration", "时长必须是数字（秒），设为 null 表示未知")
            if not math.isfinite(raw_duration):
                raise PayloadError("duration", "时长必须是有限的非负数字（秒）")
            if raw_duration < 0:
                raise PayloadError("duration", "时长不能为负数（秒）")
            duration = float(raw_duration)
        clean["duration"] = duration

    if "cover_url" in data:
        cover_url = data["cover_url"]
        if cover_url is None:
            cover_url = ""
        elif not isinstance(cover_url, str):
            raise PayloadError("cover_url", "封面地址必须是字符串")
        else:
            cover_url = cover_url.strip()
        clean["cover_url"] = cover_url

    if "description" in data:
        description = data["description"]
        if description is None:
            description = ""
        elif not isinstance(description, str):
            raise PayloadError("description", "说明必须是字符串")
        # 保留用户输入原文，包括换行与首尾空白。
        clean["description"] = description

    if "tags" in data:
        raw_tags = data["tags"]
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
        clean["tags"] = tags

    return clean


def update_track(database, track_id, data):
    """校验并更新一条曲目。返回 (record, conflicts)。

    曲目不存在时返回 (None, "not_found")；来源改成其他曲目已使用的
    文字时返回 (None, conflicts)；成功时 conflicts 为 None。
    """
    record = get_track(database, track_id)
    if record is None:
        return None, "not_found"

    clean = clean_patch_payload(data)

    new_source = clean.get("source", record["source"])
    # 来源未改变（包括旧记录继续缺失来源）时不判重；
    # 确实改成另一段文字时，排除自身后检查是否与其他曲目冲突。
    if new_source is not None and new_source != record["source"]:
        conflicts = find_conflicts(database, new_source, exclude_id=track_id)
        if conflicts:
            return None, conflicts

    assignments = []
    params = {"id": track_id}
    for field in ("title", "source", "duration", "cover_url", "description", "tags"):
        if field not in clean:
            continue
        value = clean[field]
        if field == "tags":
            value = json.dumps(value, ensure_ascii=False)
        assignments.append(f"{field} = :{field}")
        params[field] = value

    if assignments:
        database.execute(
            f"UPDATE tracks SET {', '.join(assignments)} WHERE id = :id", params
        )
        database.commit()
    return get_track(database, track_id), None


def get_track(database, track_id):
    row = database.execute(
        f"SELECT {TRACK_COLUMNS} FROM tracks WHERE id = ?", (track_id,)
    ).fetchone()
    return record_from_row(row) if row is not None else None


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


def duration_to_text(value):
    """把时长数字转成表单里可回填的文本。"""
    if value is None:
        return ""
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


FORM_FIELDS = ("title", "source", "duration", "cover_url", "description", "tags")


def render_track_form(form, error, error_field, *, action, submit_label,
                      edit_mode=False):
    """渲染收录/编辑共用的曲目表单。

    edit_mode 时不显示“另存为新版本”勾选框，并提供取消链接。
    """
    def value(name):
        return esc(form.get(name, ""))

    def inline_error(name):
        if error_field == name:
            return f'<p class="field-error">{esc(error)}</p>'
        return ""

    checkbox = ""
    if not edit_mode:
        checked = "checked" if form.get("save_as_new_version") else ""
        checkbox = (
            '<div class="checkbox-line">\n'
            '  <input type="checkbox" id="f-force" name="save_as_new_version" '
            f'value="1" {checked}>\n'
            '  <label for="f-force">即使该来源已存在，仍将本次填写'
            '<strong>另存为新版本</strong></label>\n'
            '</div>\n'
            f'  {inline_error("save_as_new_version")}\n'
        )

    cancel = ""
    if edit_mode:
        cancel = '<p class="form-cancel"><a href="/">取消编辑，返回曲目列表</a></p>\n'

    if edit_mode:
        # 编辑页每行一个标签：标签文字中的逗号、顿号等标点原样保留，
        # 不会被当作分隔符；清空某一行即删除该标签，在空行填写即新增。
        existing_tags = form.get("tags", [])
        if not isinstance(existing_tags, list):
            existing_tags = [existing_tags]
        tag_inputs = []
        for index, tag in enumerate(existing_tags, start=1):
            tag_inputs.append(
                f'<input type="text" class="tag-input" name="tag" '
                f'value="{esc(tag)}" aria-label="标签 {index}">'
            )
        for _ in range(3):
            tag_inputs.append(
                '<input type="text" class="tag-input" name="tag" value="" '
                'placeholder="（空行，可填写新标签）" aria-label="新增标签">'
            )
        tags_field = (
            '<span class="field-label">标签 <span class="hint">（每行一个标签，'
            "标签里的逗号、顿号等标点会原样保留，不会被拆开；清空某一行即删除该标签，"
            "在空行填写即新增标签；保存时自动去掉首尾空白、忽略空行，"
            '相同文字只保留第一次出现）</span></span>\n'
            + "\n".join(tag_inputs)
        )
    else:
        tags_field = (
            '<label for="f-tags">标签 <span class="hint">（可留空，'
            '多个标签用逗号分隔；自动去重）</span></label>\n'
            f'  <input type="text" id="f-tags" name="tags" value="{value("tags")}">'
        )

    return f'''<form class="track-form" method="post" action="{esc(action)}" novalidate>
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
  {tags_field}
  {inline_error("tags")}
  {checkbox}<button type="submit">{esc(submit_label)}</button>
  {cancel}</form>'''


def render_page(tracks, *, form=None, error=None, error_field=None,
                conflicts=None, highlight=None, edit_track=None,
                edit_not_found=None, edited=False):
    form = form or {}
    edit_mode = edit_track is not None

    error_html = ""
    if error:
        error_html = f'<p class="banner error" role="alert">{esc(error)}</p>'

    conflict_html = ""
    if conflicts:
        items = "".join(
            f'<li><span class="track-id">#{item["id"]}</span> {esc(item["title"])}</li>'
            for item in conflicts
        )
        if edit_mode:
            conflict_html = (
                '<div class="banner conflict" role="alert">'
                "<p><strong>该来源已被其他曲目使用，无法保存。</strong>"
                "已有记录如下：</p>"
                f'<ul class="conflict-list">{items}</ul>'
                "<p>请修改来源后重试；如需保留该来源，请取消编辑，"
                "使用收录功能另存为新版本。</p>"
                "</div>"
            )
        else:
            conflict_html = (
                '<div class="banner conflict" role="alert">'
                "<p><strong>该来源已经收录过曲目，默认不会重复新增。</strong>"
                "已有记录如下，请辨认是否是同一首：</p>"
                f'<ul class="conflict-list">{items}</ul>'
                "<p>如果这是同一来源的另一个版本（例如不同码率或重新上传），"
                "请勾选下方“另存为新版本”后再次保存，已有记录不会被修改。</p>"
                "</div>"
            )

    if edit_mode:
        form_html = render_track_form(
            form, error, error_field,
            action=f"/tracks/{edit_track['id']}/edit",
            submit_label="保存修改",
            edit_mode=True,
        )
        form_heading = (
            f'<h2>编辑曲目 <span class="track-id">#{edit_track["id"]}</span></h2>'
        )
    else:
        form_html = render_track_form(
            form, error, error_field,
            action="/",
            submit_label="保存曲目",
        )
        form_heading = '<h2 id="add">手动收录曲目</h2>'

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
        if edited:
            highlight_notice = (
                f'<p class="banner success">修改成功，曲目 <strong>#{highlight}</strong> '
                "的资料已更新，已在下方列表中显示。</p>"
            )
        else:
            highlight_notice = (
                f'<p class="banner success">收录成功，曲目 <strong>#{highlight}</strong> '
                "已加入下方列表。</p>"
            )

    not_found_html = ""
    if edit_not_found is not None:
        not_found_html = (
            f'<p class="banner error" role="alert">曲目 '
            f'<strong>#{edit_not_found}</strong> 不存在，无法编辑。</p>'
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
form.track-form .field-label{{display:block;font-weight:600;margin-top:.8rem}}
form.track-form input.tag-input{{display:block;margin-top:.3rem}}
form.track-form .hint{{font-weight:400;color:#627d98;font-size:.9em}}
form.track-form input[type=text],form.track-form textarea{{width:100%;box-sizing:border-box;padding:.45rem .6rem;border:1px solid #bcccdc;border-radius:4px;font:inherit}}
form.track-form textarea{{min-height:5.5rem;resize:vertical}}
.field-error{{color:#b3261e;margin:.25rem 0 0;font-size:.92em}}
form.track-form button{{margin-top:1.1rem;padding:.5rem 1.2rem;font:inherit;border-radius:5px;border:1px solid #14507a;background:#1769aa;color:#fff;cursor:pointer}}
.form-cancel{{margin:.6rem 0 0;font-size:.95em}}
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
.track-actions{{margin:.6rem 0 0;font-size:.95em}}
</style>
<main>
<h1>{PRODUCT}</h1>
<p>音频曲目与播放清单</p>
{highlight_notice}
{not_found_html}
{form_heading}
{conflict_html}
{error_html}
{form_html}
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
<p class="track-actions"><a href="/tracks/{record["id"]}/edit">编辑这条曲目</a></p>
</li>"""


render_track.highlight = None


def form_to_payload(form, *, split_tags=True):
    """把 application/x-www-form-urlencoded 表单转成校验器接受的字典。

    split_tags 为 True 时（首页手动收录），标签按中英文逗号和顿号分隔；
    为 False 时（编辑页），表单中每个 name="tag" 的输入行就是一个完整标签，
    行内的逗号、顿号等标点原样保留，不会被拆开。
    """
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

    if split_tags:
        tags = [part for part in re.split(r"[,，、]+", one("tags"))]
    else:
        tags = list(form.get("tag", []))

    payload = {
        "title": one("title"),
        "source": one("source"),
        "duration": duration,
        "cover_url": one("cover_url"),
        "description": one("description"),
        "tags": tags,
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

        def error_page(self, status, message, form, *, field=None, conflicts=None,
                       edit_track=None):
            page = render_page(
                list_tracks(database),
                form=form,
                error=message,
                error_field=field,
                conflicts=conflicts,
                edit_track=edit_track,
            )
            self.respond(status, page, html=True)

        def handle_page_get(self, query):
            highlight = None
            raw_highlight = query.get("highlight", [""])[0]
            if raw_highlight.isdigit():
                highlight = int(raw_highlight)
            edited = query.get("edited", [""])[0] in ("1", "true", "yes")
            self.respond(
                200,
                render_page(list_tracks(database), highlight=highlight, edited=edited),
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

        def handle_edit_get(self, track_id):
            record = get_track(database, track_id)
            if record is None:
                page = render_page(list_tracks(database), edit_not_found=track_id)
                self.respond(404, page, html=True)
                return
            form = {
                "title": record["title"],
                "source": record["source"] or "",
                "duration": duration_to_text(record["duration"]),
                "cover_url": record["cover_url"],
                "description": record["description"],
                # 每个标签占一行，标签内的标点原样保留，不拼接、不拆分。
                "tags": list(record["tags"]),
            }
            self.respond(
                200,
                render_page(list_tracks(database), form=form, edit_track=record),
                html=True,
            )

        def handle_edit_post(self, track_id):
            record = get_track(database, track_id)
            if record is None:
                page = render_page(list_tracks(database), edit_not_found=track_id)
                self.respond(404, page, html=True)
                return
            raw = self.read_body().decode("utf-8", errors="replace")
            form = parse_qs(raw, keep_blank_values=True)
            form_view = {name: form.get(name, [""])[0] for name in FORM_FIELDS}
            # 校验失败或来源冲突时，按用户这次填写的逐行标签重新渲染，
            # 保留每个标签的文字与边界。
            form_view["tags"] = form.get("tag", [])
            try:
                payload = form_to_payload(form, split_tags=False)
                # 旧记录原本没有来源时，留空的来源继续保持缺失状态，
                # 不参与来源判重；已有来源的记录清空来源会被校验拒绝。
                if record["source"] is None and not payload["source"].strip():
                    del payload["source"]
                updated, conflicts = update_track(database, track_id, payload)
            except PayloadError as exc:
                self.error_page(
                    400,
                    f"保存失败：{FIELD_LABELS.get(exc.field, '输入')}有误——{exc.message}",
                    form_view,
                    field=exc.field,
                    edit_track=record,
                )
                return
            if conflicts is not None:
                self.error_page(
                    409,
                    "保存失败：该来源已被其他曲目使用，请修改来源后重试。",
                    form_view,
                    field="source",
                    conflicts=conflicts,
                    edit_track=record,
                )
                return
            self.respond(
                303,
                "",
                html=True,
                extra_headers=[("Location", f"/?highlight={track_id}&edited=1")],
            )

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
            if record is None:
                if conflicts == "not_found":
                    self.respond(404, {"error": f"曲目 #{track_id} 不存在"})
                else:
                    self.respond(
                        409,
                        {
                            "error": "该来源已被其他曲目使用；请修改来源后重试，或取消编辑后另存新版本",
                            "field": "source",
                            "existing": conflicts,
                        },
                    )
                return
            self.respond(200, record)

        def route(self):
            location = urlsplit(self.path)
            path = location.path
            query = parse_qs(location.query)

            # 编辑曲目页面：/tracks/{id}/edit
            edit_match = re.fullmatch(r"/tracks/(\d+)/edit", path)
            if edit_match:
                track_id = int(edit_match.group(1))
                if self.command not in ("GET", "POST"):
                    self.respond(
                        405,
                        {"error": "method not allowed"},
                        extra_headers=[("Allow", "GET, POST")],
                    )
                    return
                if self.command == "GET":
                    self.handle_edit_get(track_id)
                else:
                    self.handle_edit_post(track_id)
                return

            # PATCH 曲目资料：/api/tracks/{id}
            api_match = re.fullmatch(r"/api/tracks/(\d+)", path)
            if api_match:
                track_id = int(api_match.group(1))
                if self.command != "PATCH":
                    self.respond(
                        405,
                        {"error": "method not allowed"},
                        extra_headers=[("Allow", "PATCH")],
                    )
                    return
                self.handle_api_patch(track_id)
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
                    self.handle_page_get(query)
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
