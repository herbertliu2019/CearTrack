# Game Console: 隐藏销售字段 — 周一部署说明

日期: 2026-11-07 改动,待周一部署。部署路径 `/opt/monitorcenter/`。

## 背景
销售后加的 Cyclelution 字段,测试员要在 Cyclelution 里重复录入,且 PDF《8.6.2.4-D Gaming Consoles - Factory Reset Guide》没有涉及。
决定:这些字段只在 Cyclelution 填,CearTrack entry 页面隐藏。

## 隐藏的字段
Part No.、Color、Weight、Grade、Condition、Functionality、CD/DVD Drive、Storage size、Storage type。

## 仍保留在 entry
Operator、Traveler ID、Serial、Model(含 Other)、Cosmetic(含 Other)、检查项、Data sanitization(含 Reset photo)、Notes。

## 改动的文件 (monitorcenter/)
| 文件 | 改动 |
|---|---|
| `modules/console/logic.py` | 新增 `SHOW_SALES_FIELDS = False`(PHOTO_MAX_EDGE 下方) |
| `modules/console/routes.py` | `entry()` 和 `list_tests()` 的 render_template 增加 `show_sales_fields=logic.SHOW_SALES_FIELDS` |
| `templates/console/entry.html` | 上述字段用 `{% if show_sales_fields %}` 包住(part_no/color/weight、Grade-Condition 整段、storage_size/type) |
| `templates/console/list.html` | 对应 8 列(Part No.~Storage)用同一开关包住,空行 colspan 19→11 |

## 没改的
- 数据库表/列、`_collect`/INSERT(字段缺失时存 NULL)
- `detail.html`(本来只在有值时显示,历史导入数据仍可见)
- CSV 导出(列保留,新记录这些列为空)
- 历史导入脚本 console_import.py 等

## 部署步骤
1. 备份服务器上这 4 个文件。
2. 上传到 `/opt/monitorcenter/` 对应路径:
   - `templates/console/entry.html`
   - `templates/console/list.html`
   - `modules/console/logic.py`
   - `modules/console/routes.py`
3. `sudo systemctl restart monitorcenter`
4. 浏览器强制刷新(Ctrl+F5)。

## 验证
- /console/ entry 页面:没有 Part No./Color/Weight/Grade/Condition/Functionality/CD-DVD/Storage;浏览器控制台无 JS 报错。
- 只填必填项(Operator、Serial、Model)保存成功。
- /console/tests 列表:没有上述 8 列,新记录正常显示。
- 点 CSV:列仍完整。

## 回退 / 恢复字段
- 把 `logic.py` 里 `SHOW_SALES_FIELDS` 改成 `True`,重启服务,字段和列全部恢复。
- 或用备份文件覆盖回去。

## 注意
- 开关为 False 时 Color 也隐藏;若测试员反馈需要颜色,可单独把 Color 移出 `{% if %}`。
- Grade/Condition/Functionality 组合规则仍是 "pending sales confirmation"(未强制校验)。
