#!/usr/bin/env python3
"""PATCH /api/tracks/{id} 编辑接口的回归保障。

集中覆盖修改来源时的冲突判断与保存结果：
- 同一来源的多个独立版本，编辑其中一条不能把自己当作冲突，
  来源未改变时也不能拒绝保存其他资料；
- 来源改成其他曲目已使用的文字时返回 409，existing 列出实际占用
  目标来源的记录（按 id 升序），且整条资料保持提交前状态；
- 冲突后改为未收录来源可直接保存成功；
- 旧记录（只有标识与名称、来源缺失）省略来源仍可编辑、继续缺失、
  不参与判重，补填已占用来源时同样被拒绝。

仅使用标准库，直接在子进程中启动 app.py 并通过 HTTP 打真实接口。
"""
import http.client
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent / "app.py"

SHARED_SOURCE = "/music/shared-live.flac"
TAKEN_SOURCE = "/music/taken-by-others.ape"
FRESH_SOURCE = "/music/brand-new-source.wav"


class ApiClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        headers = {}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        else:
            data = None
        conn.request(method, path, body=data, headers=headers)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
        conn.close()
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw
        return response.status, payload

    def list_tracks(self):
        status, payload = self.request("GET", "/api/tracks")
        assert status == 200, payload
        return {track["id"]: track for track in payload["tracks"]}

    def create(self, **body):
        status, payload = self.request("POST", "/api/tracks", body)
        assert status == 201, (status, payload)
        return payload

    def patch(self, track_id, body):
        return self.request("PATCH", f"/api/tracks/{track_id}", body)


class EditTrackRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="soundshelf-test-")
        cls.process = subprocess.Popen(
            [
                sys.executable,
                str(APP),
                "serve",
                "--host", "127.0.0.1",
                "--port", "0",
                "--data-dir", cls.tempdir.name,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        # --port 0 时端口由系统选择，从启动日志读取实际端口。
        deadline = time.time() + 10
        port = None
        while time.time() < deadline:
            line = cls.process.stdout.readline()
            if not line:
                if cls.process.poll() is not None:
                    raise RuntimeError(
                        f"服务提前退出：{cls.process.stdout.read()}"
                    )
                time.sleep(0.05)
                continue
            if "listening on http://" in line:
                # 形如 "SoundShelf listening on http://127.0.0.1:54321"
                port = int(line.rsplit(":", 1)[1].strip())
                break
        if port is None:
            cls.process.kill()
            raise RuntimeError("未能从启动日志中读取服务端口")
        cls.port = port
        cls.api = ApiClient("127.0.0.1", port)
        # 等待服务真正可连接。
        for _ in range(100):
            try:
                status, _ = cls.api.request("GET", "/health")
                if status == 200:
                    break
            except (ConnectionError, socket.error):
                time.sleep(0.05)
        else:
            raise RuntimeError("服务健康检查失败")

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait()
        cls.tempdir.cleanup()

    # ------------------------------------------------------------------
    # 场景一：同一来源的两个版本，编辑其中一条
    # ------------------------------------------------------------------

    def test_01_same_source_two_versions_edit_meta_without_conflict(self):
        """只改名称/说明等资料、来源不变时应成功，自身不算冲突。"""
        first = self.api.create(
            title="共享来源·初版",
            source=SHARED_SOURCE,
            duration=100,
            cover_url="",
            description="初版说明",
            tags=["摇滚"],
        )
        second = self.api.create(
            title="共享来源·再版",
            source=SHARED_SOURCE,
            duration=200.5,
            cover_url="http://cover/second.png",
            description="再版说明",
            tags=["现场", "重制"],
            save_as_new_version=True,
        )
        self.__class__.version_a = first["id"]
        self.__class__.version_b = second["id"]
        self.assertNotEqual(first["id"], second["id"])

        before = self.api.list_tracks()[first["id"]]
        status, payload = self.api.patch(
            first["id"],
            {
                "title": "共享来源·初版（修订名）",
                "description": "只改了名称之外的说明文字",
                "duration": 108.25,
                "tags": ["摇滚", "修订"],
            },
        )
        self.assertEqual(status, 200, payload)

        # 返回修改后的完整记录，原标识保持不变。
        self.assertEqual(payload["id"], before["id"])
        self.assertEqual(payload["title"], "共享来源·初版（修订名）")
        self.assertEqual(payload["source"], SHARED_SOURCE)
        self.assertEqual(payload["duration"], 108.25)
        self.assertEqual(payload["description"], "只改了名称之外的说明文字")
        self.assertEqual(payload["tags"], ["摇滚", "修订"])
        # 未提交的字段保留旧值。
        self.assertEqual(payload["cover_url"], before["cover_url"])

        tracks = self.api.list_tracks()
        # 列表能读到修改；记录数量不增加；两个版本不合并。
        self.assertEqual(len(tracks), 2)
        self.assertEqual(tracks[first["id"]]["title"], "共享来源·初版（修订名）")
        self.assertEqual(tracks[first["id"]]["source"], SHARED_SOURCE)
        self.assertEqual(
            tracks[first["id"]]["description"], "只改了名称之外的说明文字"
        )
        # 另一版本的名称、来源和其余资料保持原样。
        self.assertEqual(tracks[second["id"]]["title"], "共享来源·再版")
        self.assertEqual(tracks[second["id"]]["source"], SHARED_SOURCE)
        self.assertEqual(tracks[second["id"]]["duration"], 200.5)
        self.assertEqual(tracks[second["id"]]["cover_url"], "http://cover/second.png")
        self.assertEqual(tracks[second["id"]]["description"], "再版说明")
        self.assertEqual(tracks[second["id"]]["tags"], ["现场", "重制"])

    def test_02_resubmit_current_source_with_whitespace_is_unchanged(self):
        """再次提交当前来源（仅首尾空白不同）视为未改变，仍可保存资料。"""
        track_id = self.__class__.version_b
        before = self.api.list_tracks()[track_id]
        status, payload = self.api.patch(
            track_id,
            {
                "source": f"  {SHARED_SOURCE}\n",
                "title": "共享来源·再版（微调）",
            },
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["id"], track_id)
        self.assertEqual(payload["source"], SHARED_SOURCE)
        self.assertEqual(payload["title"], "共享来源·再版（微调）")
        # 其余字段保留旧值。
        self.assertEqual(payload["duration"], before["duration"])
        self.assertEqual(payload["cover_url"], before["cover_url"])
        self.assertEqual(payload["description"], before["description"])
        self.assertEqual(payload["tags"], before["tags"])
        # 存库后确实是 strip 过的来源，两个版本依旧并存、未合并。
        tracks = self.api.list_tracks()
        self.assertEqual(len(tracks), 2)
        self.assertEqual(tracks[track_id]["source"], SHARED_SOURCE)

    def test_03_change_to_taken_source_returns_409_and_persists_nothing(self):
        """改成其他曲目已使用的来源必须 409，即使其他字段全部合法；
        冲突列表只含实际占用目标来源的记录并按 id 升序。"""
        # 目标来源先有两条独立版本，且 id 与正在编辑的曲目交错。
        t1 = self.api.create(
            title="占用目标·甲",
            source=TAKEN_SOURCE,
            duration=11,
            description="目标来源甲",
            tags=["甲"],
        )
        t2 = self.api.create(
            title="占用目标·乙",
            source=TAKEN_SOURCE,
            duration=22,
            description="目标来源乙",
            tags=["乙"],
            save_as_new_version=True,
        )
        # 另有一条不同来源的记录，绝不能混进冲突列表。
        other = self.api.create(
            title="无关来源",
            source="/music/unrelated.mp3",
            duration=33,
        )

        editing_id = self.__class__.version_a
        before_editing = self.api.list_tracks()[editing_id]

        status, payload = self.api.patch(
            editing_id,
            {
                "source": TAKEN_SOURCE,
                "title": "试图换源后的合法新名称",
                "duration": 999.0,
                "description": "换源同时填写的合法说明",
                "tags": ["换源", "新标签"],
            },
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["field"], "source")
        existing = payload["existing"]
        # 目标来源的多个版本全部列出、按 id 升序；不含自身与无关记录。
        self.assertEqual(
            existing,
            [
                {"id": t1["id"], "title": "占用目标·甲"},
                {"id": t2["id"], "title": "占用目标·乙"},
            ],
        )
        self.assertEqual([item["id"] for item in existing], sorted(
            item["id"] for item in existing
        ))
        conflict_ids = {item["id"] for item in existing}
        self.assertNotIn(editing_id, conflict_ids)
        self.assertNotIn(other["id"], conflict_ids)

        # 冲突后整条记录必须仍是提交前的资料；目标来源各条也不受影响。
        tracks = self.api.list_tracks()
        self.assertEqual(tracks[editing_id], before_editing)
        self.assertEqual(tracks[t1["id"]]["title"], "占用目标·甲")
        self.assertEqual(tracks[t1["id"]]["source"], TAKEN_SOURCE)
        self.assertEqual(tracks[t1["id"]]["duration"], 11)
        self.assertEqual(tracks[t1["id"]]["description"], "目标来源甲")
        self.assertEqual(tracks[t1["id"]]["tags"], ["甲"])
        self.assertEqual(tracks[t2["id"]]["title"], "占用目标·乙")
        self.assertEqual(tracks[t2["id"]]["source"], TAKEN_SOURCE)
        self.assertEqual(tracks[t2["id"]]["tags"], ["乙"])
        self.assertEqual(tracks[other["id"]]["source"], "/music/unrelated.mp3")
        # 没有新增或减少记录。
        self.assertEqual(
            len(tracks),
            2 + 3,  # 同来源两版 + 目标两版 + 无关一条
        )

        self.__class__.taken_ids = (t1["id"], t2["id"])
        self.__class__.other_id = other["id"]

    def test_04_taken_source_with_surrounding_whitespace_still_conflicts(self):
        """目标来源带首尾空白时按 strip 后的文字判重，同样拒绝且不落库。"""
        editing_id = self.__class__.version_a
        before = self.api.list_tracks()[editing_id]
        status, payload = self.api.patch(
            editing_id,
            {"source": f"\t{TAKEN_SOURCE}  ", "title": "不应生效的名称"},
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(
            [item["id"] for item in payload["existing"]],
            list(self.__class__.taken_ids),
        )
        tracks = self.api.list_tracks()
        self.assertEqual(tracks[editing_id], before)
        self.assertEqual(len(tracks), 5)

    def test_05_retry_with_fresh_source_saves_normally(self):
        """冲突后改为未收录来源直接保存成功，无需先取消或另存版本。"""
        editing_id = self.__class__.version_a
        status, payload = self.api.patch(
            editing_id,
            {
                "source": FRESH_SOURCE,
                "title": "换源成功后的名称",
                "duration": 260,
                "description": "换到全新来源后保存",
                "tags": ["新来源"],
                # cover_url 不提交，沿用此前的值。
            },
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["id"], editing_id)
        self.assertEqual(payload["source"], FRESH_SOURCE)
        self.assertEqual(payload["title"], "换源成功后的名称")
        self.assertEqual(payload["duration"], 260)
        self.assertEqual(payload["description"], "换到全新来源后保存")
        self.assertEqual(payload["tags"], ["新来源"])
        self.assertEqual(payload["cover_url"], "")

        tracks = self.api.list_tracks()
        self.assertEqual(len(tracks), 5)
        self.assertEqual(tracks[editing_id]["source"], FRESH_SOURCE)
        # 曾经的冲突对象与无关记录均未被改动。
        for taken_id in self.__class__.taken_ids:
            self.assertEqual(tracks[taken_id]["source"], TAKEN_SOURCE)
        self.assertEqual(
            tracks[self.__class__.other_id]["source"], "/music/unrelated.mp3"
        )
        # 原同来源的另一版本仍指向原来源，两个版本既未合并也未误改。
        self.assertEqual(
            tracks[self.__class__.version_b]["source"], SHARED_SOURCE
        )

    # ------------------------------------------------------------------
    # 场景二：旧记录（只有标识与名称、来源缺失）
    # ------------------------------------------------------------------

    def test_06_legacy_track_omitting_source_still_editable_and_missing(self):
        """旧记录省略来源提交其他资料仍可编辑，来源继续缺失；
        不与其他缺失来源的记录产生冲突。"""
        self._insert_legacy_track("旧记录·甲")
        legacy_a = self._latest_track_id()
        self._insert_legacy_track("旧记录·乙")
        legacy_b = self._latest_track_id()

        before_a = self.api.list_tracks()[legacy_a]
        self.assertIsNone(before_a["source"])
        self.assertIsNone(self.api.list_tracks()[legacy_b]["source"])

        status, payload = self.api.patch(
            legacy_a,
            {
                "title": "旧记录·甲（补了说明）",
                "duration": 42,
                "description": "没填来源也允许保存",
                "tags": ["旧资料"],
            },
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["id"], legacy_a)
        self.assertIsNone(payload["source"])
        self.assertEqual(payload["title"], "旧记录·甲（补了说明）")
        self.assertEqual(payload["duration"], 42)
        self.assertEqual(payload["description"], "没填来源也允许保存")
        self.assertEqual(payload["tags"], ["旧资料"])
        self.assertEqual(payload["cover_url"], "")

        tracks = self.api.list_tracks()
        self.assertIsNone(tracks[legacy_a]["source"])
        self.assertIsNone(tracks[legacy_b]["source"])
        self.assertEqual(tracks[legacy_b]["title"], "旧记录·乙")
        self.__class__.legacy_a = legacy_a
        self.__class__.legacy_b = legacy_b

    def test_07_legacy_track_filling_taken_source_is_rejected_atomically(self):
        """旧记录补填一个已被占用的来源适用同样的 409 拒绝规则，
        且同次提交的其他字段也不能部分落库。"""
        legacy_a = self.__class__.legacy_a
        before = self.api.list_tracks()[legacy_a]
        status, payload = self.api.patch(
            legacy_a,
            {
                "source": TAKEN_SOURCE,
                "title": "旧记录试图补占来源",
                "duration": 7,
                "description": "不应保存",
                "tags": ["不应保存"],
            },
        )
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["field"], "source")
        self.assertEqual(
            [item["id"] for item in payload["existing"]],
            list(self.__class__.taken_ids),
        )

        tracks = self.api.list_tracks()
        # 整条记录保持提交前状态：来源仍缺失，其余资料仍是上次成功保存的值。
        self.assertEqual(tracks[legacy_a], before)
        self.assertIsNone(tracks[legacy_a]["source"])
        # 另一条缺失来源的旧记录与目标来源记录都不受影响。
        self.assertIsNone(tracks[self.__class__.legacy_b]["source"])
        for taken_id in self.__class__.taken_ids:
            self.assertEqual(tracks[taken_id]["source"], TAKEN_SOURCE)

    def test_08_legacy_track_can_fill_a_fresh_source(self):
        """旧记录补填未占用来源应成功，来源由缺失变为已填写。"""
        legacy_a = self.__class__.legacy_a
        status, payload = self.api.patch(
            legacy_a,
            {"source": "/music/legacy-filled.ogg", "title": "旧记录补全来源"},
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["source"], "/music/legacy-filled.ogg")
        self.assertEqual(payload["title"], "旧记录补全来源")
        tracks = self.api.list_tracks()
        self.assertEqual(tracks[legacy_a]["source"], "/music/legacy-filled.ogg")
        # 另一条旧记录依旧缺失来源、不参与任何判重。
        self.assertIsNone(tracks[self.__class__.legacy_b]["source"])

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _insert_legacy_track(self, title):
        """直接往 SQLite 写入一条“只有标识与名称”的旧记录。"""
        import sqlite3

        db_path = Path(self.tempdir.name) / "sound-shelf.sqlite"
        with sqlite3.connect(db_path) as conn:
            conn.execute("INSERT INTO tracks (title) VALUES (?)", (title,))
            conn.commit()

    def _latest_track_id(self):
        return max(self.api.list_tracks())


if __name__ == "__main__":
    unittest.main(verbosity=2)
