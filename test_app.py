#!/usr/bin/env python3
"""曲目收录（POST /api/tracks）与首页手动收录表单、编辑接口的回归测试。

通过子进程真实启动 SoundShelf 服务，用 HTTP 请求固定以下既有规则：

收录时的重复来源保障：
- 已有曲目使用某来源时，再提交去掉首尾空白后相同的来源（即使名称、说明等
  其他资料全部不同），未选择另存或显式传 false 都返回 409；existing 按 id
  升序列出该来源的全部已有记录（只有 id 和 title），不混入其他来源，
  拒绝时不新增记录也不改动任一已有记录。
- 仅当 save_as_new_version 为布尔值 true（或首页勾选“另存为新版本”）时
  才新增独立标识的记录：接口返回 201 和本次保存的完整曲目，首页 303 后
  列表显示新曲目与成功提示；原各版本不被覆盖或合并，列表仍按标识顺序同时
  展示。该字段传入字符串或数字一律 400 并指出字段，不能当作同意另存。
- 同名但来源不同直接收录成功；来源文字只有首尾空白被忽略，内部差异
  （含内部空白）不合并；只有标识与名称、来源缺失的旧记录不参加判重。

编辑（PATCH /api/tracks/{id}）与编辑页标签保存：
- 同一来源允许另存多个独立版本；编辑其中一条时，它自己不构成冲突，
  来源未改变（含仅首尾空白不同）时不拒绝其他资料的保存。
- 把来源改成其他曲目已使用的文字时返回 409，existing 按 id 升序列出
  实际占用该来源的记录；冲突后任何记录都不被改动，可换来源直接重试。
- 只有标识与名称、来源缺失的旧记录：省略来源可正常编辑且不参与判重；
  补填已被占用的来源同样适用拒绝保存规则。
- 编辑页（GET/POST /tracks/{id}/edit）的标签每个标签项一个输入框：
  接口收录时按完整文字保存的标签（可含换行、中英文逗号、顿号）逐框展示，
  直接保存或仅改名称不拆不并不丢；增删改只影响对应框，裁剪、忽略空项、
  按完整文字首次出现去重、清空保存为空数组；其他字段非法导致保存失败时
  整条记录不变，本次填写的标签逐框回填，修正后保存回填内容。

运行：python3 -m unittest test_app -v
"""
import html
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

APP = Path(__file__).resolve().parent / "app.py"

# 编辑页每个标签项渲染成一个同名 textarea，按文档先后顺序提交。
TAG_BOX_RE = re.compile(
    r'<textarea name="tags"[^>]*>(.*?)</textarea>', re.DOTALL
)
TEXT_INPUT_RE_TEMPLATE = (
    r'<input type="text" id="f-{fid}" name="{name}"[^>]*?value="(.*?)"[^>]*?>'
)
DESCRIPTION_RE = re.compile(
    r'<textarea id="f-description" name="description">(.*?)</textarea>',
    re.DOTALL,
)
BANNER_ERROR_RE = re.compile(
    r'<p class="banner error" role="alert">(.*?)</p>', re.DOTALL
)
BANNER_SUCCESS_RE = re.compile(
    r'<p class="banner success">(.*?)</p>', re.DOTALL
)
CONFLICT_LIST_RE = re.compile(
    r'<ul class="conflict-list">(.*?)</ul>', re.DOTALL
)
CONFLICT_ITEM_RE = re.compile(
    r'<li><span class="track-id">#(\d+)</span> (.*?)</li>', re.DOTALL
)
TRACK_LIST_ITEM_RE = re.compile(
    r'<li id="track-(\d+)"[^>]*>.*?<p class="track-title">'
    r'<span class="track-id">#\d+</span>(.*?)</p>',
    re.DOTALL,
)
FORCE_CHECKBOX_RE = re.compile(
    r'<input type="checkbox" id="f-force"[^>]*?>'
)
FIELD_ERROR_RE = re.compile(r'<p class="field-error">(.*?)</p>', re.DOTALL)


def strip_tags(markup):
    return html.unescape(re.sub(r"<[^>]+>", "", markup)).strip()


def parse_tag_boxes(page):
    """按页面顺序提取编辑页每个标签输入框的文字（已还原 HTML 转义）。"""
    return [html.unescape(raw) for raw in TAG_BOX_RE.findall(page)]


def parse_input_value(page, field_id, name):
    pattern = TEXT_INPUT_RE_TEMPLATE.format(fid=field_id, name=name)
    match = re.search(pattern, page, re.DOTALL)
    assert match is not None, f"页面中找不到字段 {name} 的输入框"
    return html.unescape(match.group(1))


def parse_conflicts(page):
    """提取首页/编辑页冲突横幅中的记录，返回 [(id, title), ...]（按展示顺序）。"""
    box = CONFLICT_LIST_RE.search(page)
    if box is None:
        return None
    return [
        (int(match.group(1)), html.unescape(match.group(2)))
        for match in CONFLICT_ITEM_RE.finditer(box.group(1))
    ]


def parse_listing_ids(page):
    """提取首页曲目列表中各曲目的 (id, title)，按页面展示顺序。"""
    return [
        (int(match.group(1)), html.unescape(match.group(2)))
        for match in TRACK_LIST_ITEM_RE.finditer(page)
    ]


def force_checkbox_present(page):
    return FORCE_CHECKBOX_RE.search(page) is not None


def force_checkbox_checked(page):
    match = FORCE_CHECKBOX_RE.search(page)
    return match is not None and "checked" in match.group(0)


def duration_text(value):
    """与 app.duration_to_text 相同的表单回填文本。"""
    if value is None:
        return ""
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)



class Server:
    """在临时数据目录上启动一个真实服务进程，测试结束后关闭。"""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.proc = subprocess.Popen(
            [
                sys.executable, str(APP), "serve",
                "--host", "127.0.0.1", "--port", "0",
                "--data-dir", str(self.data_dir),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("服务进程未能启动")
        self.base = line.split("listening on", 1)[1].strip()
        # 打印监听地址到真正接受连接之间可能有极短间隙，允许重试。
        deadline = time.monotonic() + 5
        while True:
            try:
                self.request("GET", "/health")
                return
            except ConnectionRefusedError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)

    def request(self, method, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            return exc.code, json.loads(raw) if raw else None

    def raw_request(self, method, path, body=None, content_type=None,
                    follow_redirects=True):
        """发起一次 HTTP 请求，返回 (status, headers, body_bytes)。"""
        headers = {}
        if content_type is not None:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(
            self.base + path, data=body, method=method, headers=headers,
        )
        if not follow_redirects:
            # 不跟随重定向：自定义 opener 拦截 3xx，保留状态码与 Location。
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):
                    return None

            opener = urllib.request.build_opener(NoRedirect)
            try:
                with opener.open(req) as resp:
                    return resp.status, resp.headers, resp.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.headers, exc.read()
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def get_page(self, path):
        status, headers, raw = self.raw_request("GET", path)
        return status, headers, raw.decode("utf-8")

    def post_form(self, path, fields, *, follow_redirects=True):
        """按浏览器方式提交 application/x-www-form-urlencoded 表单。

        fields 为 [(name, value), ...]，同名 name 可出现多次（编辑页每个
        标签框一个 tags 字段）；CRLF 换行原样编码，服务端负责把框内换行
        归一化为 LF。
        """
        body = urlencode(fields, doseq=True).encode("utf-8")
        status, headers, raw = self.raw_request(
            "POST", path, body,
            content_type="application/x-www-form-urlencoded",
            follow_redirects=follow_redirects,
        )
        return status, headers, raw.decode("utf-8")

    def create_track(self, **fields):
        payload = {"title": "未命名", "source": "/default"}
        payload.update(fields)
        status, body = self.request("POST", "/api/tracks", payload)
        assert status == 201, f"准备数据失败：{status} {body}"
        return body

    def insert_legacy(self, title):
        """直接写入一条只有标识与名称、来源缺失的旧记录。"""
        db = sqlite3.connect(self.data_dir / "sound-shelf.sqlite")
        try:
            cursor = db.execute("INSERT INTO tracks (title) VALUES (?)", (title,))
            db.commit()
            return cursor.lastrowid
        finally:
            db.close()

    def list_tracks(self):
        status, body = self.request("GET", "/api/tracks")
        assert status == 200, f"读取列表失败：{status} {body}"
        return body["tracks"]

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.proc.stdout.close()
        self._tmp.cleanup()


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.server = Server()
        self.addCleanup(self.server.close)

    def create_track(self, **fields):
        return self.server.create_track(**fields)

    def patch(self, track_id, payload):
        return self.server.request("PATCH", f"/api/tracks/{track_id}", payload)

    def list_tracks(self):
        return self.server.list_tracks()

    def track_by_id(self, track_id):
        for record in self.list_tracks():
            if record["id"] == track_id:
                return record
        self.fail(f"列表中找不到曲目 #{track_id}")

    # -- 编辑页（HTML 表单）-------------------------------------------------

    def get_edit_page(self, track_id):
        status, headers, page = self.server.get_page(f"/tracks/{track_id}/edit")
        self.assertEqual(status, 200, page[:500])
        return page

    def edit_form_fields(self, *, title=None, source=None, duration=None,
                         cover_url=None, description=None, tags=()):
        """构造一份编辑页表单字段（同名 tags 每个标签框一项）。

        省略的普通字段默认给空串，模拟浏览器会提交所有输入框；
        tags 为标签框文字的有序列表（可含 CRLF/LF 换行）。
        """
        fields = [
            ("title", "" if title is None else title),
            ("source", "" if source is None else source),
            ("duration", "" if duration is None else duration),
            ("cover_url", "" if cover_url is None else cover_url),
            ("description", "" if description is None else description),
        ]
        fields.extend(("tags", text) for text in tags)
        return fields

    def post_edit_form(self, track_id, fields, *, follow_redirects=False):
        return self.server.post_form(
            f"/tracks/{track_id}/edit", fields,
            follow_redirects=follow_redirects,
        )

    def assert_tag_boxes(self, page, expected):
        """逐框断言编辑页标签输入框的完整文字与先后顺序。"""
        boxes = parse_tag_boxes(page)
        self.assertEqual(
            boxes, expected,
            "标签框内容不一致：\n  实际=%r\n  期望=%r" % (boxes, expected),
        )

    def assert_form_values(self, page, *, title=None, source=None,
                           duration=None, cover_url=None, description=None):
        """断言编辑页各普通字段输入框的回填值。"""
        if title is not None:
            self.assertEqual(parse_input_value(page, "title", "title"), title)
        if source is not None:
            self.assertEqual(parse_input_value(page, "source", "source"), source)
        if duration is not None:
            self.assertEqual(
                parse_input_value(page, "duration", "duration"), duration
            )
        if cover_url is not None:
            self.assertEqual(
                parse_input_value(page, "cover-url", "cover_url"), cover_url
            )
        if description is not None:
            match = DESCRIPTION_RE.search(page)
            self.assertIsNotNone(match)
            self.assertEqual(html.unescape(match.group(1)), description)

    # -- 收录接口（POST /api/tracks）与首页收录表单 ---------------------------

    def post_json(self, payload):
        return self.server.request("POST", "/api/tracks", payload)

    def get_home(self, path="/"):
        status, headers, page = self.server.get_page(path)
        self.assertEqual(status, 200, page[:500])
        return page

    def home_form_fields(self, *, title="", source="", duration="",
                         cover_url="", description="", tags="", force=False):
        """构造一份首页收录表单字段（收录页的标签是逗号分隔的单个输入框）。"""
        fields = [
            ("title", title),
            ("source", source),
            ("duration", duration),
            ("cover_url", cover_url),
            ("description", description),
            ("tags", tags),
        ]
        if force:
            # 勾选框勾选时浏览器才会提交该字段，值为表单里的 value="1"。
            fields.append(("save_as_new_version", "1"))
        return fields

    def post_home(self, fields, *, follow_redirects=False):
        return self.server.post_form(
            "/", fields, follow_redirects=follow_redirects
        )

    def assert_home_form_retains(self, page, *, title=None, source=None,
                                 duration=None, cover_url=None,
                                 description=None, tags=None):
        """断言首页收录表单各字段回填的是本次提交时填写的原始内容。"""
        if title is not None:
            self.assertEqual(parse_input_value(page, "title", "title"), title)
        if source is not None:
            self.assertEqual(parse_input_value(page, "source", "source"), source)
        if duration is not None:
            self.assertEqual(
                parse_input_value(page, "duration", "duration"), duration
            )
        if cover_url is not None:
            self.assertEqual(
                parse_input_value(page, "cover-url", "cover_url"), cover_url
            )
        if description is not None:
            match = DESCRIPTION_RE.search(page)
            self.assertIsNotNone(match)
            # 浏览器按 CRLF 提交，失败重绘时允许保留这个换行形态。
            self.assertEqual(
                html.unescape(match.group(1)).replace("\r\n", "\n"),
                description.replace("\r\n", "\n"),
            )
        if tags is not None:
            self.assertEqual(parse_input_value(page, "tags", "tags"), tags)


class IntakeDuplicateSourceRejectTest(ServerTestCase):
    """收录时来源已被使用：默认或显式不另存都返回 409，列全冲突且不写库。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="首版说明",
            tags=["民谣", "现场"],
        )
        self.second = self.create_track(
            title="夜航·重制",
            source="/music/yehang.flac",
            duration=250,
            cover_url="https://img.example/yehang-remaster.png",
            description="重制说明",
            tags=["民谣", "重制"],
            save_as_new_version=True,
        )
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac", duration=9
        )

    def retry_payload(self, **overrides):
        """一份与已有记录名称、说明等资料全部不同的重复来源提交。"""
        payload = {
            "title": "夜航·现场录音（全新名称）",
            "source": "/music/yehang.flac",
            "duration": 260,
            "cover_url": "https://img.example/live.png",
            "description": "完全不同的现场版说明",
            "tags": ["现场", "新标签"],
        }
        payload.update(overrides)
        return payload

    def assert_rejected_with_both_occupants(self, payload):
        status, body = self.post_json(payload)
        self.assertEqual(status, 409, body)
        self.assertEqual(body["field"], "source")
        # existing 列出该来源的全部已有记录，按标识升序，
        # 每项只有 id 与名称，且不混入其他来源的曲目。
        self.assertEqual(body["existing"], [
            {"id": self.first["id"], "title": "夜航·首版"},
            {"id": self.second["id"], "title": "夜航·重制"},
        ])
        for item in body["existing"]:
            self.assertEqual(set(item.keys()), {"id", "title"})
        return body

    def test_duplicate_source_without_flag_is_rejected(self):
        # 即使名称、时长、封面、说明、标签全部不同，来源相同也默认拒绝。
        self.assert_rejected_with_both_occupants(self.retry_payload())

    def test_explicit_false_is_also_rejected(self):
        self.assert_rejected_with_both_occupants(
            self.retry_payload(save_as_new_version=False)
        )

    def test_duplicate_source_differs_only_by_surrounding_whitespace(self):
        # 只有来源首尾空白被忽略：裁剪后相同即判为重复。
        self.assert_rejected_with_both_occupants(
            self.retry_payload(source=" \t/music/yehang.flac\n  ")
        )

    def test_rejection_creates_nothing_and_changes_nothing(self):
        before = self.list_tracks()
        status, _ = self.post_json(self.retry_payload())
        self.assertEqual(status, 409)
        # 再来一次显式不另存，同样不能有任何写入。
        status, _ = self.post_json(
            self.retry_payload(save_as_new_version=False)
        )
        self.assertEqual(status, 409)

        after = self.list_tracks()
        # 记录数量与标识顺序不变，各已有记录整条资料原样保留。
        self.assertEqual(after, before)
        self.assertEqual(
            [t["id"] for t in after],
            [self.first["id"], self.second["id"], self.bystander["id"]],
        )
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)


class IntakeSaveAsNewVersionTest(ServerTestCase):
    """明确另存：得到独立新记录；同名不同来源直接成功；另存选项严格收布尔。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="首版说明",
            tags=["民谣", "现场"],
        )

    def test_true_creates_independent_record_with_submitted_data(self):
        payload = {
            "title": "夜航·现场版",
            "source": "/music/yehang.flac",
            "duration": 260,
            "cover_url": "https://img.example/live.png",
            "description": "现场版说明\n保留换行",
            "tags": ["现场", "新标签", "现场"],  # 收录时按规则去重
        }
        status, body = self.post_json(
            {**payload, "save_as_new_version": True}
        )
        self.assertEqual(status, 201, body)
        self.assertIsInstance(body["id"], int)
        self.assertNotEqual(body["id"], self.first["id"])
        # 返回本次保存的完整曲目，保存的是本次提交（含校验规整）后的资料。
        self.assertEqual(body, {
            "id": body["id"],
            "title": "夜航·现场版",
            "source": "/music/yehang.flac",
            "duration": 260,
            "cover_url": "https://img.example/live.png",
            "description": "现场版说明\n保留换行",
            "tags": ["现场", "新标签"],
        })

        tracks = self.list_tracks()
        # 列表同时能看到两个版本，按原有标识顺序展示。
        self.assertEqual([t["id"] for t in tracks],
                         [self.first["id"], body["id"]])
        # 原版本不被覆盖或合并。
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(body["id"]), body)

    def test_repeated_true_keeps_every_version_separate_and_id_ordered(self):
        second = self.post_json({
            "title": "夜航·重制",
            "source": "/music/yehang.flac",
            "duration": 250,
            "save_as_new_version": True,
        })
        self.assertEqual(second[0], 201)
        third_status, third = self.post_json({
            "title": "夜航·再版",
            "source": "/music/yehang.flac",
            "duration": 255,
            "save_as_new_version": True,
        })
        self.assertEqual(third_status, 201, third)
        self.assertNotEqual(second[1]["id"], third["id"])

        tracks = self.list_tracks()
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.first["id"], second[1]["id"], third["id"]],
        )
        self.assertEqual(
            [t["title"] for t in tracks],
            ["夜航·首版", "夜航·重制", "夜航·再版"],
        )
        # 三个版本各自保存自己的资料。
        self.assertEqual(
            self.track_by_id(second[1]["id"])["duration"], 250
        )
        self.assertEqual(
            self.track_by_id(third["id"])["duration"], 255
        )
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)

    def test_same_title_different_source_succeeds_directly(self):
        # 同名不判重：普通收录（不带另存选项）直接成功。
        status, body = self.post_json({
            "title": "夜航·首版",
            "source": "/music/yehang-cover.flac",
        })
        self.assertEqual(status, 201, body)
        self.assertEqual(body["source"], "/music/yehang-cover.flac")
        self.assertEqual(len(self.list_tracks()), 2)

    def test_internal_source_text_differences_are_not_merged(self):
        # 首尾空白之外的文字差异（查询串、内部空格等）都是不同来源，
        # 不能被额外合并，普通收录直接成功。
        for source in (
            "/music/yehang.flac?bitrate=320",
            "/music/yehang live.flac",
            "/music/YEHANG.flac",
        ):
            status, body = self.post_json(
                {"title": "另一写法", "source": source}
            )
            self.assertEqual(status, 201, (source, body))
            self.assertEqual(body["source"], source)
        self.assertEqual(len(self.list_tracks()), 4)

    def test_non_boolean_save_flag_is_400_and_never_writes(self):
        # 字符串（包括看起来像 true/false 的）与数字都不能当作同意另存。
        for bad_value in ("true", "false", "1", "0", 1, 0):
            with self.subTest(bad_value=bad_value):
                status, body = self.post_json({
                    "title": "不应写入的版本",
                    "source": "/music/yehang.flac",
                    "save_as_new_version": bad_value,
                })
                self.assertEqual(status, 400, (bad_value, body))
                # 错误必须明确指出该字段。
                self.assertEqual(body["field"], "save_as_new_version")
                self.assertIn("save_as_new_version", body["error"])

        # 所有非法尝试后仍只有最初的一条记录，没有任何新曲目写入。
        tracks = self.list_tracks()
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0], self.first)


class LegacyTrackIntakeTest(ServerTestCase):
    """只有标识与名称、来源缺失的旧记录不参加收录判重。"""

    def setUp(self):
        super().setUp()
        self.legacy_a = self.server.insert_legacy("同名曲目")
        self.legacy_b = self.server.insert_legacy("同名曲目")

    def test_legacy_name_alone_does_not_block_intake(self):
        # 旧记录名称相同不拦住新收录；两条同名旧记录也互不判重。
        status, body = self.post_json({
            "title": "同名曲目",
            "source": "/music/new.flac",
        })
        self.assertEqual(status, 201, body)
        tracks = self.list_tracks()
        self.assertEqual(
            [t["id"] for t in tracks],
            [self.legacy_a, self.legacy_b, body["id"]],
        )
        self.assertIsNone(self.track_by_id(self.legacy_a)["source"])

    def test_legacy_records_never_listed_as_source_conflicts(self):
        normal = self.create_track(title="正常曲目", source="/music/taken.flac")
        status, body = self.post_json({
            "title": "另一条同名曲目",
            "source": " /music/taken.flac ",
        })
        self.assertEqual(status, 409, body)
        # existing 只包含真正使用该来源的记录，旧记录即使同名也不混入。
        self.assertEqual(body["existing"], [
            {"id": normal["id"], "title": "正常曲目"},
        ])
        self.assertEqual(len(self.list_tracks()), 3)


class HomeIntakeDuplicateTest(ServerTestCase):
    """首页手动收录表单：重复来源拒绝并展示冲突、回填资料；勾选后另存。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243,
            description="首版说明",
            tags=["民谣"],
        )
        self.second = self.create_track(
            title="夜航·重制",
            source="/music/yehang.flac",
            duration=250,
            description="重制说明",
            tags=["重制"],
            save_as_new_version=True,
        )
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac"
        )

    def test_duplicate_without_checkbox_shows_conflicts_and_keeps_input(self):
        fields = self.home_form_fields(
            title="夜航·现场录音（全新名称）",
            source=" \t/music/yehang.flac\n ",
            duration="260",
            cover_url="https://img.example/live.png",
            description="现场版说明\n第二行",
            tags="现场, 新标签",
        )
        status, headers, page = self.post_home(fields)
        self.assertEqual(status, 409, page[:500])

        # 页面列出该来源全部已有记录（按标识升序），不含其他来源曲目。
        self.assertEqual(parse_conflicts(page), [
            (self.first["id"], "夜航·首版"),
            (self.second["id"], "夜航·重制"),
        ])
        # 错误横幅提示需要明确选择另存。
        banner = BANNER_ERROR_RE.search(page)
        self.assertIsNotNone(banner)
        self.assertIn("另存", strip_tags(banner.group(1)))

        # 本次填写的资料全部保留，包括来源首尾空白、说明换行与标签原文，
        # 勾选框保持未勾选，便于用户辨认后决定是否另存。
        self.assert_home_form_retains(
            page,
            title="夜航·现场录音（全新名称）",
            source=" \t/music/yehang.flac\n ",
            duration="260",
            cover_url="https://img.example/live.png",
            description="现场版说明\n第二行",
            tags="现场, 新标签",
        )
        self.assertTrue(force_checkbox_present(page))
        self.assertFalse(force_checkbox_checked(page))

        # 列表里不能出现这次未保存的曲目，仍是原来三条且顺序不变。
        self.assertEqual(parse_listing_ids(page), [
            (self.first["id"], "夜航·首版"),
            (self.second["id"], "夜航·重制"),
            (self.bystander["id"], "无关曲目"),
        ])

    def test_conflict_adds_nothing_and_changes_nothing(self):
        before = self.list_tracks()
        status, _, _ = self.post_home(self.home_form_fields(
            title="不应保存", source="/music/yehang.flac",
        ))
        self.assertEqual(status, 409)
        after = self.list_tracks()
        self.assertEqual(after, before)
        self.assertEqual(
            [t["id"] for t in after],
            [self.first["id"], self.second["id"], self.bystander["id"]],
        )

    def test_checking_save_as_new_version_creates_and_shows_record(self):
        fields = self.home_form_fields(
            title="夜航·现场版",
            source="/music/yehang.flac",
            duration="260",
            description="首页表单另存的版本",
            tags="现场, 新标签, 现场",
            force=True,
        )
        status, headers, page = self.post_home(fields)
        self.assertEqual(status, 303, page[:500])

        match = re.fullmatch(r"/\?highlight=(\d+)", headers["Location"])
        self.assertIsNotNone(match, headers["Location"])
        new_id = int(match.group(1))
        self.assertNotIn(new_id, (self.first["id"], self.second["id"]))

        # 跟随重定向回到列表：成功提示指向新曲目，列表按标识顺序同时展示。
        home = self.get_home(headers["Location"])
        success = BANNER_SUCCESS_RE.search(home)
        self.assertIsNotNone(success)
        notice = strip_tags(success.group(1))
        self.assertIn("收录成功", notice)
        self.assertIn(f"#{new_id}", notice)
        self.assertEqual(parse_listing_ids(home), [
            (self.first["id"], "夜航·首版"),
            (self.second["id"], "夜航·重制"),
            (self.bystander["id"], "无关曲目"),
            (new_id, "夜航·现场版"),
        ])

        # 新记录保存的是本次提交的资料；原有各版本不被覆盖或合并。
        self.assertEqual(self.track_by_id(new_id), {
            "id": new_id,
            "title": "夜航·现场版",
            "source": "/music/yehang.flac",
            "duration": 260,
            "cover_url": "",
            "description": "首页表单另存的版本",
            "tags": ["现场", "新标签"],
        })
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)
        self.assertEqual(self.track_by_id(self.second["id"]), self.second)

    def test_same_title_different_source_succeeds_from_home(self):
        status, headers, page = self.post_home(self.home_form_fields(
            title="夜航·首版",
            source="/music/yet-another.flac",
            duration="12",
        ))
        self.assertEqual(status, 303, page[:500])
        new_id = int(re.fullmatch(r"/\?highlight=(\d+)", headers["Location"]).group(1))
        self.assertEqual(len(self.list_tracks()), 4)
        self.assertEqual(
            self.track_by_id(new_id)["source"], "/music/yet-another.flac"
        )


class SameSourceVersionsEditTest(ServerTestCase):
    """同一来源另存的多个版本：编辑其中一条不应被自己或来源未变挡住。"""

    def setUp(self):
        super().setUp()
        self.first = self.create_track(
            title="夜航·首版",
            source="/music/yehang.flac",
            duration=243.5,
            cover_url="https://img.example/yehang.png",
            description="首版说明",
            tags=["民谣", "现场"],
        )
        self.second = self.create_track(
            title="夜航·重制",
            source="/music/yehang.flac",
            duration=250,
            cover_url="https://img.example/yehang-remaster.png",
            description="重制说明",
            tags=["民谣", "重制"],
            save_as_new_version=True,
        )

    def test_edit_metadata_without_source_succeeds(self):
        status, body = self.patch(self.second["id"], {
            "title": "夜航·重制（修订）",
            "description": "新的说明\n保留换行",
            "tags": ["民谣", "重制", "2026"],
        })
        self.assertEqual(status, 200, body)
        # 返回修改后的完整记录，标识不变，来源不变。
        self.assertEqual(body, {
            "id": self.second["id"],
            "title": "夜航·重制（修订）",
            "source": "/music/yehang.flac",
            "duration": 250,
            "cover_url": "https://img.example/yehang-remaster.png",
            "description": "新的说明\n保留换行",
            "tags": ["民谣", "重制", "2026"],
        })

    def test_unsubmitted_fields_keep_old_values(self):
        status, body = self.patch(self.second["id"], {"title": "只改名称"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["duration"], 250)
        self.assertEqual(body["cover_url"], "https://img.example/yehang-remaster.png")
        self.assertEqual(body["description"], "重制说明")
        self.assertEqual(body["tags"], ["民谣", "重制"])
        self.assertEqual(body["source"], "/music/yehang.flac")

    def test_resubmit_current_source_succeeds(self):
        status, body = self.patch(self.first["id"], {
            "source": "/music/yehang.flac",
            "title": "夜航·首版（校对）",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.first["id"])
        self.assertEqual(body["source"], "/music/yehang.flac")
        self.assertEqual(body["title"], "夜航·首版（校对）")

    def test_source_differing_only_by_whitespace_counts_as_unchanged(self):
        status, body = self.patch(self.first["id"], {
            "source": "  /music/yehang.flac\t\n",
            "description": "首尾空白不算改来源",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["source"], "/music/yehang.flac")
        self.assertEqual(body["description"], "首尾空白不算改来源")

    def test_other_version_untouched_and_no_merge_or_new_record(self):
        status, _ = self.patch(self.second["id"], {"title": "夜航·重制（修订）"})
        self.assertEqual(status, 200)

        tracks = self.list_tracks()
        # 记录数量不增加，两个版本仍然是各自独立的两条。
        self.assertEqual(len(tracks), 2)
        self.assertEqual([t["id"] for t in tracks],
                         [self.first["id"], self.second["id"]])
        # 列表能读到本次修改。
        self.assertEqual(self.track_by_id(self.second["id"])["title"],
                         "夜航·重制（修订）")
        # 另一版本的全部资料保持原样，没有被合并或覆盖。
        self.assertEqual(self.track_by_id(self.first["id"]), self.first)


class EditSourceConflictTest(ServerTestCase):
    """把来源改成其他曲目已使用的文字：拒绝保存且不影响任何记录。"""

    def setUp(self):
        super().setUp()
        self.edited = self.create_track(
            title="待编辑",
            source="/music/edited.flac",
            duration=100,
            cover_url="https://img.example/edited.png",
            description="原始说明",
            tags=["原始"],
        )
        self.occupied_a = self.create_track(
            title="目标来源·版本一", source="/music/taken.flac", duration=1,
        )
        self.occupied_b = self.create_track(
            title="目标来源·版本二", source="/music/taken.flac", duration=2,
            save_as_new_version=True,
        )
        self.bystander = self.create_track(
            title="无关曲目", source="/music/other.flac",
        )

    def test_conflict_returns_409_with_all_occupants(self):
        status, body = self.patch(self.edited["id"], {
            "title": "合法的新名称",
            "source": "/music/taken.flac",
            "duration": 180,
            "description": "合法的新说明",
            "tags": ["合法", "标签"],
        })
        self.assertEqual(status, 409, body)
        self.assertEqual(body["field"], "source")
        # 目标来源的多个版本全部列出，按标识升序；
        # 不包含正在编辑的曲目，也不包含其他来源的记录。
        self.assertEqual(body["existing"], [
            {"id": self.occupied_a["id"], "title": "目标来源·版本一"},
            {"id": self.occupied_b["id"], "title": "目标来源·版本二"},
        ])

    def test_conflict_leaves_every_record_unchanged(self):
        status, _ = self.patch(self.edited["id"], {
            "title": "合法的新名称",
            "source": "/music/taken.flac",
            "duration": 180,
            "description": "合法的新说明",
            "tags": ["合法", "标签"],
        })
        self.assertEqual(status, 409)

        tracks = self.list_tracks()
        self.assertEqual(len(tracks), 4)
        # 正在编辑的记录仍是提交前的整条资料，没有保存一部分。
        self.assertEqual(self.track_by_id(self.edited["id"]), self.edited)
        # 目标来源的各条记录与无关记录都不受影响。
        self.assertEqual(self.track_by_id(self.occupied_a["id"]), self.occupied_a)
        self.assertEqual(self.track_by_id(self.occupied_b["id"]), self.occupied_b)
        self.assertEqual(self.track_by_id(self.bystander["id"]), self.bystander)

    def test_retry_with_free_source_saves_without_cancelling(self):
        status, _ = self.patch(self.edited["id"], {"source": "/music/taken.flac"})
        self.assertEqual(status, 409)

        # 不取消编辑、不另存版本，直接换成未收录的来源重新提交。
        status, body = self.patch(self.edited["id"], {
            "title": "合法的新名称",
            "source": "/music/fresh.flac",
            "duration": 180,
            "description": "合法的新说明",
            "tags": ["合法", "标签"],
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {
            "id": self.edited["id"],
            "title": "合法的新名称",
            "source": "/music/fresh.flac",
            "duration": 180,
            "cover_url": "https://img.example/edited.png",
            "description": "合法的新说明",
            "tags": ["合法", "标签"],
        })
        self.assertEqual(self.track_by_id(self.edited["id"]), body)

    def test_conflict_whitespace_trimmed_before_comparison(self):
        # 目标来源按去掉首尾空白后的文字判断。
        status, body = self.patch(self.edited["id"], {
            "source": "  /music/taken.flac  ",
        })
        self.assertEqual(status, 409, body)
        self.assertEqual(len(body["existing"]), 2)


class LegacyTrackEditTest(ServerTestCase):
    """只有标识与名称、来源缺失的旧记录的兼容行为。"""

    def setUp(self):
        super().setUp()
        self.legacy_a = self.server.insert_legacy("旧记录·甲")
        self.legacy_b = self.server.insert_legacy("旧记录·乙")
        self.normal = self.create_track(
            title="正常曲目", source="/music/normal.flac",
        )

    def test_legacy_edit_omitting_source_succeeds_and_stays_missing(self):
        status, body = self.patch(self.legacy_a, {
            "title": "旧记录·甲（补全）",
            "duration": 90,
            "description": "补写的说明",
            "tags": ["旧"],
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["id"], self.legacy_a)
        self.assertIsNone(body["source"])
        self.assertEqual(body["title"], "旧记录·甲（补全）")
        self.assertEqual(body["duration"], 90)
        # 另一条同样缺失来源的旧记录不构成冲突，也不受影响。
        other = self.track_by_id(self.legacy_b)
        self.assertIsNone(other["source"])
        self.assertEqual(other["title"], "旧记录·乙")

    def test_legacy_assigning_occupied_source_is_rejected(self):
        status, body = self.patch(self.legacy_a, {
            "source": "/music/normal.flac",
            "title": "不应保存的名称",
        })
        self.assertEqual(status, 409, body)
        self.assertEqual(body["field"], "source")
        self.assertEqual(body["existing"], [
            {"id": self.normal["id"], "title": "正常曲目"},
        ])
        # 拒绝后旧记录保持提交前的整条资料。
        record = self.track_by_id(self.legacy_a)
        self.assertIsNone(record["source"])
        self.assertEqual(record["title"], "旧记录·甲")

    def test_legacy_assigning_free_source_succeeds(self):
        status, body = self.patch(self.legacy_a, {
            "source": "/music/legacy-filled.flac",
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["source"], "/music/legacy-filled.flac")
        self.assertEqual(body["title"], "旧记录·甲")


class EditPageTagBoxesTest(ServerTestCase):
    """打开编辑页：接口收录的标签逐项各占一个输入框，换行与标点原样保留。

    准备数据时标签同时覆盖：
    - 多行标签（两行分别为“自然”“雨声”）；
    - 与多行标签中某一行全文相同的独立标签（单独一项“雨声”）；
    - 含中文逗号、顿号等标点的完整标签（“晨间，鸟鸣、溪流”）。
    """

    MULTILINE_TAG = "自然\n雨声"
    SHARED_LINE_TAG = "雨声"
    PUNCT_TAG = "晨间，鸟鸣、溪流"
    INITIAL_TAGS = [MULTILINE_TAG, SHARED_LINE_TAG, PUNCT_TAG]

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=212,
            description="清晨山涧录音",
            tags=self.INITIAL_TAGS,
        )
        self.track_id = self.track["id"]

    def test_api_stored_tags_keep_full_text(self):
        # 前置保障：接口收录后三项按完整文字独立保存，顺序不变。
        self.assertEqual(self.track["tags"], self.INITIAL_TAGS)

    def test_edit_page_renders_one_box_per_tag_preserving_newlines(self):
        page = self.get_edit_page(self.track_id)
        # 三项已有标签各占一个框，末尾另有一个空框供新增；
        # 多行标签仍在同一个框内，不被换行拆开；标点完整保留。
        self.assert_tag_boxes(
            page,
            [self.MULTILINE_TAG, self.SHARED_LINE_TAG, self.PUNCT_TAG, ""],
        )
        # 页面正文必须真实包含多行文字的两行（而不是被并成一行）。
        self.assertIn("自然\n雨声", page)
        # 含标点的标签作为一个整体出现在同一个框内。
        self.assertIn("晨间，鸟鸣、溪流", page)
        # 其他字段也按当前资料回填。
        self.assert_form_values(
            page,
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration="212",
            description="清晨山涧录音",
        )

    def test_save_without_touching_tags_keeps_text_and_order(self):
        # 模拟用户打开编辑页：各框原样提交（框内换行以浏览器的 CRLF 发送），
        # 只把名称改成“山涧晨曲（定稿）”，不增删任何标签框。
        tags_crlf = [tag.replace("\n", "\r\n") for tag in self.INITIAL_TAGS]
        status, headers, _ = self.post_edit_form(
            self.track_id,
            self.edit_form_fields(
                title="山涧晨曲（定稿）",
                source="/music/shanjian.flac",
                duration="212",
                description="清晨山涧录音",
                tags=tags_crlf,
            ),
        )
        self.assertEqual(status, 303, headers)
        self.assertEqual(
            headers["Location"],
            f"/?highlight={self.track_id}&edited=1",
        )

        record = self.track_by_id(self.track_id)
        self.assertEqual(record["title"], "山涧晨曲（定稿）")
        # 三项标签的完整文字与先后顺序完全不变：多行标签没有被按行拆开，
        # 独立的“雨声”没有与多行标签合并，标点标签原样保留。
        self.assertEqual(record["tags"], self.INITIAL_TAGS)

        # 再次打开编辑页，页面内容与保存结果一致。
        page = self.get_edit_page(self.track_id)
        self.assert_tag_boxes(
            page,
            [self.MULTILINE_TAG, self.SHARED_LINE_TAG, self.PUNCT_TAG, ""],
        )
        self.assert_form_values(page, title="山涧晨曲（定稿）", duration="212")

    def test_save_changing_only_title_via_full_form_keeps_tags(self):
        # 即使标签框里带有首尾空白与 CRLF，保存时仅裁剪该项首尾空白，
        # 框内换行与标点保留；只改名称时标签结果与收录时一致。
        tags_with_ws = [
            "  " + self.MULTILINE_TAG.replace("\n", "\r\n") + "\t",
            " " + self.SHARED_LINE_TAG + " ",
            " " + self.PUNCT_TAG + " ",
        ]
        status, _, _ = self.post_edit_form(
            self.track_id,
            self.edit_form_fields(
                title="山涧晨曲·改名",
                source="/music/shanjian.flac",
                tags=tags_with_ws,
            ),
        )
        self.assertEqual(status, 303)
        self.assertEqual(self.track_by_id(self.track_id)["tags"],
                         self.INITIAL_TAGS)


class EditPageTagChangesTest(ServerTestCase):
    """编辑页上对标签的修改、增删、去重与清空的保存结果。"""

    A = "自然\n雨声"
    B = "雨声"
    C = "晨间，鸟鸣、溪流"

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="林间录音",
            source="/music/linjian.flac",
            duration=100,
            tags=[self.A, self.B, self.C],
        )
        self.track_id = self.track["id"]

    def save_tags(self, tags, **extra):
        fields = self.edit_form_fields(
            title="林间录音",
            source="/music/linjian.flac",
            duration="100",
            tags=tags,
            **extra,
        )
        status, headers, page = self.post_edit_form(self.track_id, fields)
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            headers["Location"], f"/?highlight={self.track_id}&edited=1"
        )
        return self.track_by_id(self.track_id)

    def test_editing_one_box_changes_only_that_tag(self):
        # 只修改第二个框（独立的“雨声”），其余两项文字与位置不变。
        record = self.save_tags([self.A, "雨声·加大声", self.C])
        self.assertEqual(record["tags"], [self.A, "雨声·加大声", self.C])

    def test_adding_and_removing_boxes_keeps_relative_order(self):
        # 在开头新增、中间删除（删掉独立的“雨声”）、末尾再新增：
        # 其余标签保持原先的相对先后关系。
        record = self.save_tags(["新增·开头", self.A, self.C, "新增·末尾"])
        self.assertEqual(
            record["tags"],
            ["新增·开头", self.A, self.C, "新增·末尾"],
        )

        # 再次打开页面逐框核对，末尾仍附空框。
        page = self.get_edit_page(self.track_id)
        self.assert_tag_boxes(
            page, ["新增·开头", self.A, self.C, "新增·末尾", ""]
        )

    def test_trim_blank_items_and_dedup_by_full_text(self):
        record = self.save_tags([
            "  " + self.A.replace("\n", "\r\n") + "  ",  # 去首尾空白后等于 A
            "",                                            # 空项忽略
            "   \r\n  ",                                   # 只有空白，忽略
            self.B,
            self.A,                                        # 与首项全文相同，去重
            "雨声\n自然",                                  # 行集合相同但顺序不同，保留
            self.C,
            " " + self.C + "\t",                           # 裁剪后与 C 相同，去重
        ])
        self.assertEqual(
            record["tags"],
            [self.A, self.B, "雨声\n自然", self.C],
        )
        # 共享某一行（“雨声”）的不同标签继续各自保留，互不合并。
        tags = record["tags"]
        self.assertIn(self.A, tags)
        self.assertIn(self.B, tags)
        self.assertIn("雨声\n自然", tags)

    def test_punctuation_inside_tag_is_never_a_separator(self):
        record = self.save_tags([
            "前奏，间奏、尾奏",
            "前奏",
            "一行写两样：风，雨、雷",
        ])
        self.assertEqual(
            record["tags"],
            ["前奏，间奏、尾奏", "前奏", "一行写两样：风，雨、雷"],
        )

    def test_clear_all_tags_saves_empty_array(self):
        record = self.save_tags([])
        self.assertEqual(record["tags"], [])

        # 再次打开编辑页只有一个空框，可以继续填写新标签。
        page = self.get_edit_page(self.track_id)
        self.assert_tag_boxes(page, [""])

        record = self.save_tags(["重新填写的标签", "第二个"])
        self.assertEqual(record["tags"], ["重新填写的标签", "第二个"])


class EditPageTagSaveFailureTest(ServerTestCase):
    """其他字段非法导致保存失败：记录不写入，标签逐框回填，修正后可保存。"""

    MULTILINE_TAG = "自然\n雨声"
    SHARED_LINE_TAG = "雨声"
    PUNCT_TAG = "晨间，鸟鸣、溪流"
    INITIAL_TAGS = [MULTILINE_TAG, SHARED_LINE_TAG, PUNCT_TAG]

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration=212,
            description="清晨山涧录音",
            tags=self.INITIAL_TAGS,
        )
        self.track_id = self.track["id"]

    def test_negative_duration_blocks_save_and_reprints_every_tag_box(self):
        # 用户已修改标签（改一项、新增一项，框内换行以 CRLF 提交），
        # 但把时长误填成负数。
        edited_tags_lf = ["自然\n风声", self.SHARED_LINE_TAG, self.PUNCT_TAG,
                          "新增标签\n第二行"]
        edited_tags_crlf = [t.replace("\n", "\r\n") for t in edited_tags_lf]
        fields = self.edit_form_fields(
            title="山涧晨曲",
            source="/music/shanjian.flac",
            duration="-5",
            description="清晨山涧录音",
            tags=edited_tags_crlf,
        )
        status, headers, page = self.post_edit_form(self.track_id, fields)
        self.assertEqual(status, 400)

        # 页面明确指出时长错误。
        banner = BANNER_ERROR_RE.search(page)
        self.assertIsNotNone(banner)
        self.assertIn("时长", strip_tags(banner.group(1)))
        field_errors = [strip_tags(raw) for raw in FIELD_ERROR_RE.findall(page)]
        self.assertTrue(
            any("时长" in text for text in field_errors),
            f"时长字段旁应显示错误，实际：{field_errors}",
        )

        # 本次曲目的任何资料都没有写入：记录与提交前完全一致。
        self.assertEqual(self.track_by_id(self.track_id), self.track)

        # 用户填写的每项标签逐框回填：项内换行归一化为 LF 保留，
        # 项与项之间的边界不被拆开或合并，顺序不变；末尾附空框。
        self.assert_tag_boxes(page, edited_tags_lf + [""])
        # 出错的时长也回填用户填写的内容，便于修正。
        self.assert_form_values(page, duration="-5")

    def test_fix_duration_after_failure_saves_reprinted_tags(self):
        # 第一次保存：负数时长失败。
        edited_tags_lf = ["自然\n风声", self.SHARED_LINE_TAG, self.PUNCT_TAG,
                          "新增标签\n第二行"]
        edited_tags_crlf = [t.replace("\n", "\r\n") for t in edited_tags_lf]
        status, _, failed_page = self.post_edit_form(
            self.track_id,
            self.edit_form_fields(
                title="山涧晨曲",
                source="/music/shanjian.flac",
                duration="-5",
                description="清晨山涧录音",
                tags=edited_tags_crlf,
            ),
        )
        self.assertEqual(status, 400)

        # 从失败页面逐框取回回填的标签（连同末尾空框），仅把时长修正为正数
        # 后再次保存——模拟用户在回填页面上直接重试。
        reprinted_boxes = parse_tag_boxes(failed_page)
        self.assertEqual(reprinted_boxes, edited_tags_lf + [""])
        status, headers, page = self.post_edit_form(
            self.track_id,
            self.edit_form_fields(
                title="山涧晨曲",
                source="/music/shanjian.flac",
                duration="240",
                description="清晨山涧录音",
                # 回填文字中的 LF 再次按浏览器方式以 CRLF 发送。
                tags=[box.replace("\n", "\r\n") for box in reprinted_boxes],
            ),
        )
        self.assertEqual(status, 303, page[:500])
        self.assertEqual(
            headers["Location"], f"/?highlight={self.track_id}&edited=1"
        )

        record = self.track_by_id(self.track_id)
        # 保存的是失败前用户填写的标签（末尾空框按空项忽略），
        # 没有回到旧标签，顺序也不变。
        self.assertEqual(record["tags"], edited_tags_lf)
        self.assertEqual(record["duration"], 240)

        # 再次打开编辑页，页面内容与保存结果一致。
        reopened = self.get_edit_page(self.track_id)
        self.assert_tag_boxes(reopened, edited_tags_lf + [""])
        self.assert_form_values(reopened, duration="240")


if __name__ == "__main__":
    unittest.main()
