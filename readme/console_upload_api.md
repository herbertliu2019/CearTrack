# CearTrack Game Console — 外部上传接口使用说明

把 Game Console 测试结果（JSON，可附 PDF）上传到 CearTrack。

## 1. 接口

| 项 | 值 |
|---|---|
| URL | `http://192.168.30.18:5004/console/api/upload`（Nginx：`http://192.168.30.18/console/api/upload`） |
| 方法 | `POST` |
| 认证 | Header `X-API-Key: ceartrack-upload-2026` |

## 2. 调用方式

**A. JSON + 可选 PDF（multipart）**
```
curl -H "X-API-Key: ceartrack-upload-2026" \
     -F json=@result.json -F pdf=@result.pdf \
     http://192.168.30.18:5004/console/api/upload
```
- 字段名固定：`json`（必填）、`pdf`（可选，必须是真实 PDF）。

**B. 仅 JSON（原始 body）**
```
curl -H "X-API-Key: ceartrack-upload-2026" -H "Content-Type: application/json" \
     --data-binary @result.json \
     http://192.168.30.18:5004/console/api/upload
```

Python 示例：
```python
import requests
r = requests.post("http://192.168.30.18:5004/console/api/upload",
                  headers={"X-API-Key": "ceartrack-upload-2026"},
                  files={"json": open("result.json", "rb"), "pdf": open("result.pdf", "rb")})
print(r.status_code, r.json())
```

## 3. JSON 格式

```json
{
  "serial_no": "ABC123",
  "manufacturer": "Sony",
  "model": "PlayStation 4",
  "operator": "tech01",
  "traveler_id": "T-1001",
  "result": "Pass",
  "items": {"Power": "Pass", "Video (HDMI)": "Fail"},
  "cosmetic": ["Scratches"],
  "sanitize": {
    "method": "Factory Reset",
    "result": "Pass",
    "date": "2026-11-11",
    "storage_type": "HDD",
    "storage_size": "500 GB",
    "hdd_sn": "",
    "hdd_traveler_id": ""
  },
  "grade": "A",
  "condition": "C4 - Used Good",
  "functionality": "F3 - Key Functions Working",
  "cd_dvd": "No",
  "part_no": "",
  "color": "",
  "weight": 0.0,
  "notes": ""
}
```

**必填**：`serial_no`、`manufacturer`、`model`、`operator`。其余可选。

| 字段 | 说明 |
|---|---|
| `items` | 对象 `{"项目名": "状态"}`，或数组 `[{"name":"..","status":".."}]`。状态可用：`Pass`/`Passed`/`OK`、`Fail`/`Failed`、`N/A`/`NA`/`Skip`（不区分大小写），其他值报错。项目名按该机型已有的检测项 label/code 匹配（不区分大小写）；未上报的项目记为 N/A；匹配不上的项目写入备注 `[unmapped items: ...]`。 |
| `sanitize.method` | `EPS` / `Factory Reset`（默认）/ `Manual Delete` / `Pre-Sanitization` / `No data` / `Locked`。`EPS` 必须同时提供 `date`、`hdd_sn`、`hdd_traveler_id`。 |
| `sanitize.result` | `Pass` / `Fail` / `N/A`；缺省按 method 默认值。`Locked` 强制 Fail，`No data` 强制 N/A。 |
| `cosmetic` | 字符串数组，如 `Minor scratches/blemishes`、`Scratches`、`Dents`、`Cracked case`、`Missing faceplate`、`Missing cover`、`Missing feet`、`Discoloration`、`Heavy wear`。 |
| `grade` | `A`–`F`（单个字母）。 |
| `condition` | 完整字符串：`C1 - Damaged` … `C9 - New Open-Box`（如 `C4 - Used Good`）。 |
| `storage_type` | 如 `HDD`、`SSD`、`eMMC`、`Flash Storage`、`Internal Flash`。 |
| `weight` | 非负数字。 |

## 4. 服务端行为

- **Result / Marks 由 CearTrack 重新计算**，不采信上传的 `result`；该值仅作为 `ext_result` 记录，若与计算结果不一致，详情页会提示。
- **去重**：对 JSON 原文件做 SHA-256，完全相同的文件重复上传不会新增记录。
- **复测**：同一 `serial_no`（不区分大小写）再次上传，旧记录自动标记为被取代。
- **新机型**：manufacturer + model 不存在时自动创建（使用通用检测项）。
- 原始 JSON/PDF 保存在服务器，详情页可下载；列表 Source 列显示 `API`。

## 5. 返回值

| HTTP | 内容 | 含义 |
|---|---|---|
| 200 | `{"ok":true,"id":123,"result":"Pass","marks":"...","retest":false}` | 保存成功 |
| 200 | `{"ok":true,"duplicate":true,"id":123,...}` | 文件已上传过，未重复保存 |
| 400 | `{"ok":false,"errors":["..."]}` | JSON 无效 / 缺必填 / 字段取值非法 |
| 401 | `{"ok":false,"errors":["Invalid or missing X-API-Key"]}` | Key 错误 |
| 500 | `{"ok":false,"errors":["Server error while saving"]}` | 服务端错误，联系 Cear Testing |

## 6. 注意

- 上述字段名为 CearTrack 约定格式；如果你们工具输出的 JSON 字段不同，请发一份真实样本给我们，由服务端适配，无需你们改格式。
- API Key 仅限内部使用，勿外传。
