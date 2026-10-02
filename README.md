# SoundShelf

音频曲目与播放清单。

需要Python 3.10 或更新版本，包含标准库 sqlite3。

查看命令帮助：

```sh
python3 app.py --help
```

启动本地服务：

```sh
python3 app.py serve --host 127.0.0.1 --port 8080 --data-dir data
```

打开 http://127.0.0.1:8080 查看首页，手动收录音频曲目并查看列表。Ctrl+C 停止服务。`--data-dir` 指定本地业务数据目录（SQLite 数据库），重启时继续使用同一目录，已收录的内容和各个版本都会保留。

## 收录规则

- 名称和来源必填，去掉首尾空白后不能为空。
- 时长可留空（表示未知）；填写时必须是有限的非负数，允许 0 和小数。
- 封面地址可留空，保存时不检查远端文件是否可访问。
- 说明可留空并保留换行。
- 标签可留空；填写的标签去掉首尾空白、忽略空项并按首次出现的顺序去重。
- 来源按去掉首尾空白后的文字判重：已有相同来源时默认不新增，接口返回 409 并带回该来源已有记录的标识和名称；明确选择「另存为新版本」后再次保存，才新增独立标识的记录。已有记录不会被覆盖，同名但来源不同的曲目可以直接收录。
- 页面与接口遵循相同规则。

## 接口

- `GET /health` 返回服务状态和产品名称。
- `GET /api/tracks` 返回曲目列表，`tracks` 数组按标识升序，每项包含 `id`、`title` 及本次收录的完整资料（`source`、`duration`、`cover`、`notes`、`tags`）。
- `POST /api/tracks` 收录一首曲目。请求体为 JSON：

```json
{
  "title": "晨间播客第 1 期",
  "source": "https://example.com/audio.mp3",
  "duration": 123.5,
  "cover": "https://example.com/cover.jpg",
  "notes": "说明文字，\n保留换行",
  "tags": ["播客", "晨间"],
  "save_as_new_version": false
}
```

  - `title`、`source` 必填；`duration` 可省略或为 `null`；`cover`、`notes` 可省略；`tags` 为字符串数组，可省略；`save_as_new_version` 为布尔值，可省略，默认 `false`。
  - 收录成功返回 `201`，响应体为 `{"track": { ...完整记录... }}`。
  - 来源已存在且未指定另存为新版本时返回 `409`，响应体包含 `error` 原因和 `tracks` 数组（每项含已有记录的 `id` 与 `title`）。
  - 无效 JSON、字段类型错误或字段值不合法时返回 `400`，响应体 `{"error": "明确原因"}`，不写入数据。
- 未知路径返回 404，已知路径不支持的方法返回 405。

```sh
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/api/tracks
curl -X POST http://127.0.0.1:8080/api/tracks \
  -H "Content-Type: application/json" \
  -d '{"title":"晨间播客第 1 期","source":"https://example.com/audio.mp3","duration":123.5,"tags":["播客","播客"]}'
```
