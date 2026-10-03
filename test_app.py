#!/usr/bin/env python3
"""曲目编辑接口（PATCH /api/tracks/{id}）与编辑页标签保存的回归测试。

通过子进程真实启动 SoundShelf 服务，用 HTTP 请求固定以下既有规则：

- 同一来源允许另存多个独立版本；编辑其中一条时，它自己不构成冲突，
  来源未改变（含仅首尾空白不同）时不拒绝其他资料的保存。
- 把来源改成其他曲目已使用的文字时返回 409，existing 按 id 升序列出
  实际占用该来源的记录；冲突后任何记录都不被改动，可换来源直接重试。
- 只有标识与名称、来源缺失的旧记录：省略来源可正常编辑且不参与判重；
  补填已被占用的来源同样适用拒绝保存规则。
- 编辑页标签按输入框区分：接口收录的标签即使含有换行或中英文逗号、
  顿号，打开编辑页后每项独占一个输入框；未改标签直接保存（例如只改
  名称）时各项完整文字、项内换行与先后顺序全部保持不变；某一行恰好
  等于另一个标签的全文也不会把多行项拆开或把两项合并。
- 修改、新增、删除标签框只影响对应标签，其余项保持相对顺序；保存时
  每项去掉首尾空白、忽略空项，仅完整文字相同才按首次出现去重；全部
  删空保存为空数组，之后可以重新填写。
- 其他字段不合法（如时长为负）导致保存失败时整条记录保持原样，
  本次填写的标签逐框回填（保留项内换行与项之间的边界）；修正后再次
  保存使用回填内容，不回退旧标签、不改变顺序。

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

    def get_page(self, path):
        """读取页面，返回 (status, 最终 URL, HTML 文本)，自动跟随重定向。"""
        req = urllib.request.Request(self.base + path, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.geturl(), resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.geturl(), exc.read().decode("utf-8")

    def post_form(self, path, fields):
        """提交 application/x-www-form-urlencoded 表单。

        fields 为 [(name, value), ...]：同名 tags 出现几次就提交几个框，
        框内换行与标点原样编码。返回 (status, 最终 URL, HTML 文本)，
        成功时页面逻辑是 303 跳转，这里自动跟随到列表页。
        """
        body = urlencode(fields, doseq=True).encode("utf-8")
        req = urllib.request.Request(
            self.base + path,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.geturl(), resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.geturl(), exc.read().decode("utf-8")

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

    def open_edit_page(self, track_id):
        return self.server.get_page(f"/tracks/{track_id}/edit")

    def save_edit_form(self, track_id, fields):
        return self.server.post_form(f"/tracks/{track_id}/edit", fields)

    @staticmethod
    def tag_boxes(page_html):
        """按先后顺序提取编辑页每个标签输入框中的文字。

        文字来自服务端 HTML 转义后的 textarea 内容，这里反转义还原；
        框内换行保留为 \\n，框之间的顺序即提交顺序。末尾用于新增的空框
        同样会出现在结果中。
        """
        blocks = re.findall(
            r'<textarea name="tags"[^>]*>(.*?)</textarea>',
            page_html,
            flags=re.DOTALL,
        )
        return [html.unescape(block) for block in blocks]

    @staticmethod
    def form_fields_from(record, *, tags=None, duration=None, **overrides):
        """按记录当前资料构造一份完整的编辑表单字段。

        tags 为标签框文字列表（None 时沿用记录已保存的标签），每项一个
        同名 tags 字段；duration 为文本框内容（None 时沿用记录时长）。
        """
        if duration is None:
            value = record["duration"]
            duration = "" if value is None else str(value)
        if tags is None:
            tags = list(record["tags"])
        fields = [
            ("title", overrides.get("title", record["title"])),
            ("source", overrides.get("source", record["source"] or "")),
            ("duration", duration),
            ("cover_url", overrides.get("cover_url", record["cover_url"])),
            ("description", overrides.get("description", record["description"])),
        ]
        fields.extend(("tags", text) for text in tags)
        return fields


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


class EditPageTagPersistenceTest(ServerTestCase):
    """接口收录的含换行/标点标签：编辑页逐框展示，未改标签直接保存不变。"""

    INITIAL_TAGS = ["自然\n雨声", "雨声", "晨间，鸟鸣、溪流"]

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="林间晨曲",
            source="/music/forest-morning.flac",
            duration=120,
            description="雨后的树林",
            tags=list(self.INITIAL_TAGS),
        )

    def test_edit_page_shows_one_box_per_tag_with_newlines_and_punctuation(self):
        status, _, page = self.open_edit_page(self.track["id"])
        self.assertEqual(status, 200)
        # 每个标签项独占自己的输入框，顺序与收录时一致；框内换行、
        # 中英文逗号与顿号原样保留；末尾另附一个空框供新增。
        self.assertEqual(
            self.tag_boxes(page),
            ["自然\n雨声", "雨声", "晨间，鸟鸣、溪流", ""],
        )

    def test_save_without_touching_tags_keeps_text_and_order(self):
        # 打开编辑页后只改名称，标签按页面上的框原样回提（含多行项）。
        _, _, page = self.open_edit_page(self.track["id"])
        boxes = self.tag_boxes(page)[:-1]  # 去掉末尾用于新增的空框
        self.assertEqual(boxes, self.INITIAL_TAGS)
        fields = self.form_fields_from(
            self.track, tags=boxes, title="林间晨曲（更名）"
        )
        status, final_url, list_page = self.save_edit_form(self.track["id"], fields)
        self.assertEqual(status, 200)
        self.assertTrue(
            final_url.endswith(f"/?highlight={self.track['id']}&edited=1"),
            final_url,
        )
        self.assertIn("修改成功", list_page)

        record = self.track_by_id(self.track["id"])
        self.assertEqual(record["title"], "林间晨曲（更名）")
        # 完整文字与先后顺序逐项不变：多行项没有被按行拆开，
        # 整项“雨声”也没有与多行项中的某一行合并或被删除。
        self.assertEqual(record["tags"], self.INITIAL_TAGS)

        # 列表页同样把每个标签按完整文字渲染（换行仍在同一个标签内）。
        for tag in self.INITIAL_TAGS:
            self.assertIn(f'<span class="tag">{tag}</span>', list_page)

        # 再次打开编辑页，每个标签仍各自回到自己的输入框。
        _, _, reopened = self.open_edit_page(self.track["id"])
        self.assertEqual(
            self.tag_boxes(reopened),
            ["自然\n雨声", "雨声", "晨间，鸟鸣、溪流", ""],
        )


class EditPageTagEditingTest(ServerTestCase):
    """编辑页改动标签：修改/新增/删除、去首尾空白、忽略空项、去重、清空。"""

    INITIAL_TAGS = ["一", "二\n雨声", "雨声", "晨间，鸟鸣、溪流", "末"]

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="标签编辑演练",
            source="/music/tag-edit.flac",
            duration=60,
            tags=list(self.INITIAL_TAGS),
        )

    def save_tags(self, tag_boxes):
        fields = self.form_fields_from(self.track, tags=tag_boxes)
        status, final_url, page = self.save_edit_form(self.track["id"], fields)
        self.assertEqual(status, 200, page[:500])
        self.assertTrue(final_url.endswith("&edited=1"), final_url)
        return self.track_by_id(self.track["id"])

    def test_modify_one_box_changes_only_that_tag(self):
        boxes = list(self.INITIAL_TAGS)
        boxes[1] = "二\n风声"
        record = self.save_tags(boxes)
        self.assertEqual(
            record["tags"],
            ["一", "二\n风声", "雨声", "晨间，鸟鸣、溪流", "末"],
        )

    def test_add_box_appends_without_reordering_others(self):
        record = self.save_tags(self.INITIAL_TAGS + ["新增标签"])
        self.assertEqual(
            record["tags"],
            ["一", "二\n雨声", "雨声", "晨间，鸟鸣、溪流", "末", "新增标签"],
        )

    def test_delete_single_line_tag_keeps_multiline_tag_intact(self):
        # 删除整项恰好等于多行项某一行的“雨声”，多行项不能被拆动。
        record = self.save_tags(["一", "二\n雨声", "晨间，鸟鸣、溪流", "末"])
        self.assertEqual(
            record["tags"], ["一", "二\n雨声", "晨间，鸟鸣、溪流", "末"]
        )

    def test_delete_multiline_tag_keeps_shared_line_tag(self):
        # 反过来删除多行项，只共享某一行文字的“雨声”仍作为独立标签保留。
        record = self.save_tags(["一", "雨声", "晨间，鸟鸣、溪流", "末"])
        self.assertEqual(
            record["tags"], ["一", "雨声", "晨间，鸟鸣、溪流", "末"]
        )

    def test_trim_ignore_empty_and_dedup_by_full_text(self):
        boxes = [
            "  一\t",          # 去掉整项首尾空白后为“一”
            "",                # 空项忽略
            "  二\n雨声  ",    # 只去整项首尾空白，项内换行保留
            "雨声",            # 与多行项仅共享一行：两项都保留
            "二\n雨声",        # 与更早一项完整文字相同：重复项忽略
            "   \t ",          # 纯空白项忽略
            "晨间，鸟鸣、溪流",
            "末",
            "末",              # 完整文字相同的重复项：保留第一次出现
        ]
        record = self.save_tags(boxes)
        self.assertEqual(
            record["tags"],
            ["一", "二\n雨声", "雨声", "晨间，鸟鸣、溪流", "末"],
        )

    def test_form_crlf_newlines_normalized_to_lf(self):
        # 浏览器按 CRLF 提交框内换行，保存结果统一为 LF，与接口收录一致。
        record = self.save_tags(["甲\r\n乙", "雨声"])
        self.assertEqual(record["tags"], ["甲\n乙", "雨声"])

    def test_clear_all_tags_then_readd(self):
        # 页面脚本始终保留至少一个框；全部删空时提交的就是一个空框。
        record = self.save_tags([""])
        self.assertEqual(record["tags"], [])

        # 再次打开编辑页只有一个空框，可继续填写新标签。
        _, _, page = self.open_edit_page(self.track["id"])
        self.assertEqual(self.tag_boxes(page), [""])

        record = self.save_tags(["新标签甲", "新标签乙\n第二行"])
        self.assertEqual(record["tags"], ["新标签甲", "新标签乙\n第二行"])
        _, _, page = self.open_edit_page(self.track["id"])
        self.assertEqual(
            self.tag_boxes(page),
            ["新标签甲", "新标签乙\n第二行", ""],
        )


class EditPageTagSaveFailureTest(ServerTestCase):
    """其他字段不合法时保存失败：不写入，标签逐框回填，修正后按回填内容保存。"""

    def setUp(self):
        super().setUp()
        self.track = self.create_track(
            title="保存失败演练",
            source="/music/retry.flac",
            duration=30,
            description="旧说明",
            tags=["旧标签", "保持\n原样"],
        )

    def test_negative_duration_blocks_save_and_refills_each_tag_box(self):
        attempted_tags = [
            "新标签一\n第二行",
            "晨间，鸟鸣、溪流",
            "  带首尾空白  ",
            "",
        ]
        fields = self.form_fields_from(
            self.track,
            tags=attempted_tags,
            duration="-5",
            title="保存失败演练（改名）",
            description="不应保存的新说明",
        )
        status, _, page = self.save_edit_form(self.track["id"], fields)
        self.assertEqual(status, 400)
        # 页面明确指出时长错误（而不是标签或其他字段）。
        self.assertIn("保存失败：时长有误", page)
        self.assertIn("不能为负", page)

        # 本次填写的每一项标签逐框回填：框内换行、标点、首尾空白和
        # 项之间的边界（含提交的空框）全部保留，末尾再附一个空框。
        self.assertEqual(
            self.tag_boxes(page),
            ["新标签一\n第二行", "晨间，鸟鸣、溪流", "  带首尾空白  ", "", ""],
        )

        # 保存失败是整条拒绝：曲目的任何资料都保持提交前的样子。
        self.assertEqual(self.track_by_id(self.track["id"]), self.track)

        # 直接按回填的各框修正时长后再次保存：保存的是回填内容，
        # 不会回到旧标签，各项先后顺序不变（首尾空白照常规整、空项忽略）。
        refilled = self.tag_boxes(page)
        fields = self.form_fields_from(self.track, tags=refilled, duration="45")
        status, final_url, _ = self.save_edit_form(self.track["id"], fields)
        self.assertEqual(status, 200)
        self.assertTrue(final_url.endswith("&edited=1"), final_url)

        record = self.track_by_id(self.track["id"])
        self.assertEqual(record["duration"], 45)
        # 失败时尝试修改的名称与说明同样没有被写入。
        self.assertEqual(record["title"], "保存失败演练")
        self.assertEqual(record["description"], "旧说明")
        self.assertEqual(
            record["tags"],
            ["新标签一\n第二行", "晨间，鸟鸣、溪流", "带首尾空白"],
        )

        # 再次打开编辑页，保存结果逐框呈现，而不是旧标签。
        _, _, reopened = self.open_edit_page(self.track["id"])
        self.assertEqual(
            self.tag_boxes(reopened),
            ["新标签一\n第二行", "晨间，鸟鸣、溪流", "带首尾空白", ""],
        )


if __name__ == "__main__":
    unittest.main()
