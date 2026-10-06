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


# ---------------------------------------------------------------------------
# 字段级校验与规整：收录与编辑共用同一套规则。
#
# 每个函数接收该字段的原始取值，返回可直接入库的规整结果；
# 不合法输入抛 PayloadError。“字段未提交”的语义（收录补默认值、
# 编辑保留旧值）由各入口函数处理，不在字段规则里。


def clean_title_value(title):
    """名称：必须是字符串，去掉首尾空白后不能为空。"""
    if not isinstance(title, str):
        raise PayloadError("title", "名称必须是字符串")
    title = title.strip()
    if not title:
        raise PayloadError("title", "名称去掉首尾空白后不能为空")
    return title


def clean_source_value(source, *, empty_message):
    """来源：必须是字符串，按去掉首尾空白后的文字保存。

    空白来源的提示由调用方给出（收录与编辑的措辞不同）。
    """
    if not isinstance(source, str):
        raise PayloadError("source", "来源必须是字符串")
    source = source.strip()
    if not source:
        raise PayloadError("source", empty_message)
    return source


def clean_duration_value(raw_duration, *, unknown_hint):
    """时长：None 表示未知；否则必须是有限的非负数字（秒），允许零和
    小数，布尔值不能当作秒数。类型错误的提示由调用方给出。"""
    if raw_duration is None:
        return None
    if isinstance(raw_duration, bool) or not isinstance(raw_duration, (int, float)):
        raise PayloadError("duration", f"时长必须是数字（秒），{unknown_hint}")
    if not math.isfinite(raw_duration):
        raise PayloadError("duration", "时长必须是有限的非负数字（秒）")
    if raw_duration < 0:
        raise PayloadError("duration", "时长不能为负数（秒）")
    return float(raw_duration)


def clean_cover_url_value(cover_url):
    """封面地址：None 视为留空；必须是字符串，去掉首尾空白。"""
    if cover_url is None:
        return ""
    if not isinstance(cover_url, str):
        raise PayloadError("cover_url", "封面地址必须是字符串")
    return cover_url.strip()


def clean_description_value(description):
    """说明：None 视为留空；必须是字符串，保留用户输入原文，
    包括换行与首尾空白。"""
    if description is None:
        return ""
    if not isinstance(description, str):
        raise PayloadError("description", "说明必须是字符串")
    return description


def clean_tags_value(raw_tags):
    """标签：None 视为空数组；每项必须是字符串，按该项完整文字去掉
    首尾空白、忽略空项，并按首次出现顺序去重。项内文字（含换行、
    中英文逗号和顿号）原样保留，绝不拆分成多项。"""
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
    return tags


def clean_payload(data):
    """校验并规整一份曲目资料，返回可直接入库的 dict。

    页面表单转换后的字典与外部 JSON 请求共用这套规则：名称与来源
    必填，选填资料未提交时使用默认值。任何不合法输入都抛
    PayloadError，且不会写入数据。
    """
    if not isinstance(data, dict):
        raise PayloadError(None, "请求体必须是 JSON 对象")

    title = data.get("title")
    if title is None:
        raise PayloadError("title", "名称为必填项")
    title = clean_title_value(title)

    source = data.get("source")
    if source is None:
        raise PayloadError("source", "来源为必填项")
    source = clean_source_value(source, empty_message="来源去掉首尾空白后不能为空")

    duration = clean_duration_value(
        data.get("duration"), unknown_hint="留空表示未知"
    )
    cover_url = clean_cover_url_value(data.get("cover_url"))
    description = clean_description_value(data.get("description"))
    tags = clean_tags_value(data.get("tags"))

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

    字段规则与收录共用同一实现；未提交的字段由调用方合并旧值，
    这里不补任何默认值。任何不合法输入都抛 PayloadError，
    且不会写入数据。
    """
    if not isinstance(data, dict):
        raise PayloadError(None, "请求体必须是 JSON 对象")

    clean = {}

    if "title" in data:
        clean["title"] = clean_title_value(data["title"])

    if "source" in data:
        source = data["source"]
        # 已有来源不能清空：明确提交 null 或空白来源都拒绝。
        if source is None:
            raise PayloadError("source", "来源不能清空；如不再收录该来源，请取消编辑")
        clean["source"] = clean_source_value(
            source, empty_message="来源不能清空；如不再收录该来源，请取消编辑"
        )

    if "duration" in data:
        clean["duration"] = clean_duration_value(
            data["duration"], unknown_hint="设为 null 表示未知"
        )

    if "cover_url" in data:
        clean["cover_url"] = clean_cover_url_value(data["cover_url"])

    if "description" in data:
        clean["description"] = clean_description_value(data["description"])

    if "tags" in data:
        clean["tags"] = clean_tags_value(data["tags"])

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


def normalize_newlines(text):
    """把提交内容的 CRLF/CR 换行统一成 LF。

    浏览器提交 textarea 时会把框内换行按 CRLF 编码，旧记录也可能直接
    收录了 CR；比较与保存都以 LF 形态进行，避免同一段文字因换行写法
    不同被当成已修改。
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def textarea_content(text):
    """生成 textarea 起始标签后、结束标签前的安全文本。

    HTML 解析规则会忽略 textarea 起始标签之后紧跟的第一个换行（CRLF
    算作一个），因此原文以换行开头时要额外补一个换行，框内才能还原
    开头空行；原文不以换行开头时不能补，否则会凭空多出一行。
    """
    if text.startswith(("\n", "\r")):
        return "\n" + esc(text)
    return esc(text)


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

    # 名称按文字保存，内部换行与空格都是名称的一部分：用多行输入框完整
    # 呈现已保存名称（含开头空行，由 textarea_content 抵消 HTML 解析
    # 吞掉的第一个换行），框高随实际行数自适应。
    title_text = form.get("title", "")
    title_rows = min(
        max(1, len(re.findall(r"\r\n|\r|\n", title_text)) + 1), 10
    )
    # 来源按文字保存，内部换行与空格都是来源的一部分：用多行输入框完整
    # 呈现已保存来源（含开头空行，由 textarea_content 抵消 HTML 解析
    # 吞掉的第一个换行），框高随实际行数自适应。
    source_text = form.get("source", "")
    source_rows = min(max(1, source_text.count("\n") + 1), 10)

    if edit_mode:
        # 编辑页每个标签项一个独立输入框：标签文字内部的换行保留在
        # 该项自己的输入框中，不会再把一个标签拆成几个；标签内的逗号、
        # 顿号等标点同样原样保留。修改某个框即修改该标签，删除某个框
        # （“删除这一项”按钮）即删除该标签，末尾的空框用于新增标签。
        tag_items = form.get("tags_items")
        if tag_items is None:
            tag_items = [""]
        # 每个框配一个隐藏域，记录它对应的原始标签序号：保存时据此把
        # 未修改的框还原成原始完整文字（含原来的 LF/CRLF/CR 换行写法），
        # 新增的框没有序号。隐藏域与输入框同在一个条目里，删除该框时
        # 一起移除；每个框都带隐藏域（新增框留空），保证提交后同名
        # 字段按顺序一一对应。
        tag_refs = list(form.get("tags_refs") or [])
        if len(tag_refs) < len(tag_items):
            tag_refs += [""] * (len(tag_items) - len(tag_refs))
        tag_inputs = []
        for tag_text, tag_ref in zip(tag_items, tag_refs):
            # 框高随该项实际行数自适应，让项内换行一目了然。
            rows = min(max(2, tag_text.count("\n") + 2), 10)
            tag_inputs.append(
                '<div class="tag-edit-item">\n'
                f'  <textarea name="tags" rows="{rows}">{esc(tag_text)}</textarea>\n'
                f'  <input type="hidden" name="tags_ref" value="{esc(tag_ref)}">\n'
                '  <button type="button" class="tag-remove" '
                'data-tag-remove="1">删除这一项</button>\n'
                '</div>'
            )
        tags_field = (
            '<label>标签 <span class="hint">（可留空。<strong>每个输入框是一个标签项</strong>，'
            '一个标签可以在框内换行写成多行；标签内的逗号、顿号等标点会原样保留，'
            '不会被当作标签之间的分隔。修改某个框的文字只影响该标签；'
            '用“删除这一项”删除标签，用下方空框或“再加一项”新增标签；'
            '全部删空则保存为无标签。每项自动去掉首尾空白、忽略空项、'
            '完整文字相同的标签只保留第一次出现）</span></label>\n'
            '<div class="tag-edit-list" data-tag-list="1">\n'
            f'  {"".join(tag_inputs)}\n'
            '</div>\n'
            '<button type="button" class="tag-add" data-tag-add="1">再加一项</button>\n'
            f'  {inline_error("tags")}'
        )
    else:
        tags_field = (
            '<label for="f-tags">标签 <span class="hint">（可留空，'
            '多个标签用逗号分隔；自动去重）</span></label>\n'
            f'  <input type="text" id="f-tags" name="tags" value="{value("tags")}">\n'
            f'  {inline_error("tags")}'
        )

    return f'''<form class="track-form" method="post" action="{esc(action)}" novalidate>
  <label for="f-title">名称 <span class="hint">（必填，可在框内换行写成多行；按文字原样保存，只裁掉首尾空白，内部换行与空格都会保留）</span></label>
  <textarea id="f-title" name="title" class="title-box" rows="{title_rows}">{textarea_content(title_text)}</textarea>
  {inline_error("title")}
  <label for="f-source">来源 <span class="hint">（必填，网址或本地文件路径，按文字原样保存，内部换行与空格都会保留，不检查能否播放）</span></label>
  <textarea id="f-source" name="source" class="source-box" rows="{source_rows}">{textarea_content(source_text)}</textarea>
  {inline_error("source")}
  <label for="f-duration">时长 <span class="hint">（秒，可留空表示未知；允许 0 和小数）</span></label>
  <input type="text" id="f-duration" name="duration" inputmode="decimal" value="{value("duration")}">
  {inline_error("duration")}
  <label for="f-cover-url">封面地址 <span class="hint">（可留空，不会检查远端文件）</span></label>
  <input type="text" id="f-cover-url" name="cover_url" value="{value("cover_url")}">
  {inline_error("cover_url")}
  <label for="f-description">说明 <span class="hint">（可留空，保留换行）</span></label>
  <textarea id="f-description" name="description">{textarea_content(form.get("description", ""))}</textarea>
  {inline_error("description")}
  {tags_field}
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
form.track-form .hint{{font-weight:400;color:#627d98;font-size:.9em}}
form.track-form input[type=text],form.track-form textarea{{width:100%;box-sizing:border-box;padding:.45rem .6rem;border:1px solid #bcccdc;border-radius:4px;font:inherit}}
form.track-form textarea{{min-height:5.5rem;resize:vertical}}
form.track-form textarea.source-box{{min-height:2.4rem}}
form.track-form textarea.title-box{{min-height:2.4rem}}
.field-error{{color:#b3261e;margin:.25rem 0 0;font-size:.92em}}
form.track-form button{{margin-top:1.1rem;padding:.5rem 1.2rem;font:inherit;border-radius:5px;border:1px solid #14507a;background:#1769aa;color:#fff;cursor:pointer}}
.form-cancel{{margin:.6rem 0 0;font-size:.95em}}
.checkbox-line{{margin-top:1rem}}
.checkbox-line label{{display:inline;font-weight:400}}
ol.tracks{{list-style:none;padding:0;display:flex;flex-direction:column;gap:1rem}}
ol.tracks li{{border:1px solid #d9e2ec;border-radius:8px;padding:.8rem 1.1rem;background:#fff}}
ol.tracks li.highlight{{border-color:#1769aa;box-shadow:0 0 0 2px rgba(23,105,170,.18)}}
.track-id{{display:inline-block;min-width:2.6em;color:#627d98;font-variant-numeric:tabular-nums}}
.track-title{{font-size:1.12em;font-weight:700;margin:0 0 .4rem;white-space:pre-wrap}}
.track-meta{{display:grid;grid-template-columns:5.5rem 1fr;gap:.15rem .8rem;margin:0}}
.track-meta dt{{color:#627d98}}
.track-meta dd{{margin:0;word-break:break-all}}
.notes{{white-space:pre-wrap;word-break:normal}}
.unfilled{{color:#829ab1}}
.tag{{display:inline-block;background:#e4e7eb;border-radius:999px;padding:.05rem .7rem;margin:.1rem .25rem .1rem 0;font-size:.88em}}
.tag-edit-list{{display:flex;flex-direction:column;gap:.5rem;margin-top:.3rem}}
.tag-edit-item{{display:flex;gap:.5rem;align-items:flex-start}}
.tag-edit-item textarea{{flex:1;min-height:2.6rem}}
form.track-form button.tag-remove{{margin:0;white-space:nowrap;align-self:center;padding:.3rem .7rem;font-size:.88em;border:1px solid #b3261e;background:#fff;color:#b3261e;cursor:pointer}}
form.track-form button.tag-add{{margin-top:.6rem;padding:.35rem .9rem;font-size:.92em;border:1px solid #14507a;background:#fff;color:#1769aa;cursor:pointer}}
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
<script>
(function () {{
  // 仅编辑页存在标签项列表：新增一个空输入框、删除指定的一项。
  // 不改动任何已有框的文字与顺序，保存时浏览器按框的先后顺序提交同名 tags 字段。
  var list = document.querySelector('[data-tag-list]');
  if (!list) return;
  document.addEventListener('click', function (event) {{
    if (event.target.hasAttribute('data-tag-add')) {{
      var item = document.createElement('div');
      item.className = 'tag-edit-item';
      var box = document.createElement('textarea');
      box.name = 'tags';
      box.rows = 2;
      // 新增的框没有对应的原始标签，隐藏序号留空，与既有框的字段一一对应。
      var ref = document.createElement('input');
      ref.type = 'hidden';
      ref.name = 'tags_ref';
      ref.value = '';
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'tag-remove';
      remove.setAttribute('data-tag-remove', '1');
      remove.textContent = '删除这一项';
      item.appendChild(box);
      item.appendChild(ref);
      item.appendChild(remove);
      list.appendChild(item);
      box.focus();
    }} else if (event.target.hasAttribute('data-tag-remove')) {{
      var row = event.target.closest('.tag-edit-item');
      if (row && list.children.length > 1) {{
        row.remove();
      }} else if (row) {{
        // 至少保留一个框：清空文字让该项按空项忽略，而不是移除提交字段。
        row.querySelector('textarea').value = '';
      }}
    }}
  }});
}})();
</script>
</html>"""


def render_track(record, highlight=None):
    legacy = record["source"] is None
    highlighted = " highlight" if record["id"] == highlight else ""

    def unfilled(text="未填写"):
        return f'<span class="unfilled">{text}</span>'

    # 旧记录（无来源）只把来源显示为未填写；其余资料按实际保存的值展示，
    # 仍为空时才沿用旧记录原来的占位表现。
    source_cell = unfilled() if legacy else esc(record["source"])

    if record["duration"] is None:
        duration_cell = unfilled() if legacy else unfilled("未知")
    else:
        duration_cell = esc(format_duration(record["duration"]))

    cover_cell = esc(record["cover_url"]) if record["cover_url"] else unfilled()

    if record["description"]:
        notes_cell = esc(record["description"])
    else:
        notes_cell = unfilled() if legacy else ""

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


# ---------------------------------------------------------------------------
# 编辑页文字字段的“浏览器换行兼容”。
#
# form_to_payload 已把 textarea 提交的 CRLF/CR 换行归一化为 LF（浏览器
# 总按 CRLF 提交框内换行，旧记录也可能直接收录 CR）；保存前再统一判断
# 归一化后的提交文字是否意味着内容真的改变：
#   - 名称、来源、标签项（trim_outer=True）：换行归一化并去掉整段首尾
#     空白后相同即视为未改动，首尾增删空白沿用各自既有的裁剪规则；
#   - 说明（trim_outer=False）：只归一化换行，开头/结尾空行与首尾空格
#     都是实际内容，空字符串与只含空白的说明不能混为一谈。
# 判定未改动时保留库里的完整原文（逐字节保留 LF/CRLF/CR 写法），确实
# 改动时才采用本次填写（网页改动的换行统一为 LF）。这套判断只服务编辑
# 表单保存：直接打接口提交的文字不经过这里，不新增任何规整规则。


def edit_text_unchanged(submitted, original, *, trim_outer):
    """编辑表单提交的文字（换行已归一化为 LF）相对原文是否未改动。

    original 是库里保存的完整原文，可能使用 LF、CRLF 或 CR 换行；
    比较前对原文做同样的换行归一化，避免浏览器提交写法被当成改动。
    trim_outer 为 True 时（名称、来源、标签项）忽略整段首尾空白，
    为 False 时（说明）首尾空白也逐字参与比较。
    """
    baseline = normalize_newlines(original)
    if trim_outer:
        return submitted.strip() == baseline.strip()
    return submitted == baseline


def reconcile_edit_text(submitted, original, *, trim_outer):
    """编辑页单个文字字段最终保存的文字。

    用户未改动时返回原文完整字节（含原有 LF/CRLF/CR 换行写法），
    确实改动时返回本次填写内容（换行已统一为 LF）。
    """
    if edit_text_unchanged(submitted, original, trim_outer=trim_outer):
        return original
    return submitted


def omit_unchanged_edit_field(payload, field, original, *, trim_outer):
    """把编辑页的一个整段文字字段并入 PATCH 数据。

    用户未改动时直接从 payload 删除该字段：update_track 对“未提交”的
    字段保留旧值，原文（换行写法、说明首尾空白）得以逐字节保留；确实
    改动时保留 payload 中已归一化为 LF 的填写内容，首尾空白仍由各字段
    既有的统一校验规则处理（名称、来源裁整段首尾，说明完整保留）。
    """
    if edit_text_unchanged(payload[field], original, trim_outer=trim_outer):
        del payload[field]


def reconcile_edit_tags(submitted, refs, originals):
    """把编辑页提交的标签逐项对齐到原始标签，决定最终保存的完整文字。

    submitted 为各框文字（已归一化为 LF），refs 为各框对应的原始标签
    序号（新增框为空，序号越界或缺失时按新增处理）。框内文字是否改动
    与名称、来源共用同一判断（换行归一化、去掉整项首尾空白后比较）：
    未修改时保留原始项的完整原文（含 LF/CRLF/CR 换行写法），浏览器显示
    与提交换行的写法差异不算修改；否则按本次填写的文字保存。首尾空白
    裁剪、空项忽略与按最终完整文字去重仍交由统一校验规则处理。
    """
    final = []
    for index, text in enumerate(submitted):
        ref = refs[index].strip() if index < len(refs) else ""
        if ref.isdigit():
            position = int(ref)
            if position < len(originals):
                final.append(
                    reconcile_edit_text(
                        text, originals[position], trim_outer=True
                    )
                )
                continue
        final.append(text)
    return final


def form_to_payload(form, *, edit_mode=False):
    """把 application/x-www-form-urlencoded 表单转成校验器接受的字典。

    edit_mode 时每个同名 tags 字段就是一个完整标签项：项内换行、逗号、
    顿号等文字全部按原文保留，绝不再按行或标点拆分一个标签；
    首尾空白、空项与去重仍交由统一校验规则处理。
    收录模式（edit_mode=False）则按中英文逗号和顿号分隔。
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

    if edit_mode:
        # 每个同名字段对应编辑页的一个标签输入框，字段内部的换行原样保留；
        # 浏览器按 CRLF 提交，统一归一化为 LF，使保存结果与接口原文收录一致。
        tags = [normalize_newlines(part) for part in form.get("tags", [])]
        # 说明框同样会被浏览器按 CRLF 提交：先归一化为 LF，调用方再据此
        # 判断用户是否真的改过说明，改了才按本次文字（LF 换行）保存。
        description = normalize_newlines(one("description"))
    else:
        tags = [part for part in re.split(r"[,，、]+", one("tags"))]
        description = one("description")

    payload = {
        # 名称框也是多行输入框：浏览器按 CRLF 提交框内换行，统一归一化为
        # LF，使网页填写的名称与接口按文字收录的同一段名称一致；编辑时
        # 调用方再据此判断用户是否真的改过名称。
        "title": normalize_newlines(one("title")),
        # 来源框也是多行输入框：浏览器按 CRLF 提交框内换行，统一归一化为
        # LF，使网页填写的来源与接口按文字收录的同一段来源一致；编辑时
        # 调用方再据此判断用户是否真的改过来源。
        "source": normalize_newlines(one("source")),
        "duration": duration,
        "cover_url": one("cover_url"),
        "description": description,
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
            # 失败重绘时按 LF 回填名称框（浏览器以 CRLF 提交框内换行），
            # 名称中的内部换行与空格按本次填写完整保留。
            form_view["title"] = normalize_newlines(form_view["title"])
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
                # 每个标签项一个输入框，完整保留各项的文字（含项内换行）、边界和顺序；
                # 隐藏域记录各项对应的原始标签序号，保存时据此还原未修改项的原文。
                "tags_items": list(record["tags"]) + [""],
                "tags_refs": [str(i) for i in range(len(record["tags"]))] + [""],
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
            # 失败重绘时按 LF 回填名称框、来源框与说明框（浏览器以 CRLF
            # 提交换行），名称的内部换行与空格（含连续空行、各行文字）、
            # 来源的内部换行与空格、说明的开头空行、段落空行、结尾空行与
            # 首尾空格都按本次填写完整保留。
            form_view["title"] = normalize_newlines(form_view["title"])
            form_view["source"] = normalize_newlines(form_view["source"])
            form_view["description"] = normalize_newlines(
                form_view["description"]
            )
            # 失败重绘时逐框回填用户本次填写的标签，保留项之间的边界与
            # 项内换行，连同各项对应的原始标签序号一起回填：修正出错字段后
            # 再次保存，未修改的项仍能还原原始完整文字，不因经过错误页面
            # 丢掉一项或改写原文。末尾再附一个空框便于继续新增。
            submitted_tags = [
                normalize_newlines(part) for part in form.get("tags", [])
            ]
            submitted_refs = form.get("tags_ref", [])
            form_view["tags_items"] = submitted_tags + [""]
            form_view["tags_refs"] = submitted_refs + [""]
            try:
                payload = form_to_payload(form, edit_mode=True)
                # 用户没有修改的框（文字与内部空行不变，或仅整项首尾增加
                # 空白）保留原始标签的完整文字：LF/CRLF/CR 换行写法不被
                # 改写，仅换行写法不同的两项也不会被合并；确实修改或新增
                # 的项按本次填写（换行统一为 LF）保存，去重以最终要保存
                # 的完整文字为准。
                payload["tags"] = reconcile_edit_tags(
                    submitted_tags, submitted_refs, record["tags"]
                )
                # 名称、来源、说明统一按编辑页文字字段处理：浏览器提交时
                # 换行已归一化为 LF，归一化后的提交文字与原文按各字段规则
                # 比较相同（名称、来源还会去掉整段首尾空白，说明则逐字比较）
                # 即视为未改动，不提交该字段，由 update_track 的“未提交保留
                # 旧值”语义逐字节保留原文——LF/CRLF/CR 换行写法、说明的
                # 首尾空白、空串与纯空白说明的区别都不被改写；仅首尾增删
                # 空白沿用名称、来源既有的裁剪规则，不算改动内部内容。
                # 确实改动时才按本次填写（换行统一为 LF）保存：名称、来源
                # 只裁整段首尾空白，说明完整保留。
                omit_unchanged_edit_field(
                    payload, "title", record["title"], trim_outer=True
                )
                omit_unchanged_edit_field(
                    payload, "description", record["description"],
                    trim_outer=False,
                )
                # 旧记录原本没有来源时，留空的来源继续保持缺失状态：同样
                # 不提交该字段，也不参与来源判重；已有来源的记录清空来源
                # 会被校验拒绝。
                if record["source"] is None:
                    if not payload["source"].strip():
                        del payload["source"]
                else:
                    omit_unchanged_edit_field(
                        payload, "source", record["source"], trim_outer=True
                    )
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
