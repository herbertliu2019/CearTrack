TASK-04 到 TASK-08 完成后执行：

# 1. 全量扫描
cd /opt/monitorcenter
python3 -m modules.wipe.scanner \
  --config config/wipe_paths.json --full

# 2. 验证总数
sqlite3 data/wipe_index.db "SELECT COUNT(*) FROM wipe_records;"

# 3. 按 source 分布
sqlite3 data/wipe_index.db \
  "SELECT source, COUNT(*) FROM wipe_records GROUP BY source;"

# 4. 查看错误
sqlite3 data/wipe_index.db \
  "SELECT COUNT(*) FROM scan_errors;"
sqlite3 data/wipe_index.db \
  "SELECT log_path, error_msg FROM scan_errors LIMIT 10;"

# 5. 测试搜索（替换为实际存在的 SN）
curl "http://localhost:5000/wipe/api/search?q=82TPGJ8XQ69K"
# 返回该硬盘全部历史记录，第一条 is_latest=true

# 6. 测试今日统计
curl http://localhost:5000/wipe/api/today

# 期望结果：
# - 总记录数与实际文件数接近
# - scan_errors 数量合理（<1%）
# - source 分布符合预期
# - search 返回正确结果