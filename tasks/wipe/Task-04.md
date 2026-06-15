文件：/opt/monitorcenter/modules/wipe/scanner.py

如果文件已存在，先读取现有代码，
在不修改已有方法的前提下，补充或修正以下内容：

class WipeScanner:
  def __init__(self, log_root, db_path, win_share_root)

  def make_win_path(self, log_path: Path) -> str
    去掉 /mnt/WIPE 前缀，正斜杠→反斜杠，拼接 win_share_root

  def get_source(self, log_path: Path) -> str
    根据路径判断 source：
      /eps/ 且无 /Makor/ → "eps"
      /pxe/ 且无 /Makor/ → "pxe"
      /eps/ 且有 /Makor/ → "makor_eps"
      /pxe/ 且有 /Makor/ → "makor_pxe"
      其他              → "unknown"

  def should_skip(self, f: Path) -> bool
    返回 True（跳过）的条件：
      - 扩展名 .txt
      - 扩展名 .xml 且路径不含 Makor
      - 路径含 /Verify/

  def parse_file(self, f: Path) -> dict | None
    根据扩展名选择 parser：
      .log → parse_log(f)
      .xml → parse_makor_xml(f)
      其他 → None

  def collect_all(self) -> list[Path]
    rglob("*") 扫描 log_root 下所有文件
    过滤：not should_skip(f)
    返回排序后的列表

  def collect_incremental(self) -> list[Path]
    1. SELECT log_path FROM wipe_records → Python set
    2. collect_all() 全部文件
    3. 返回：全部文件 - 已索引文件
    不依赖 mtime

  def _process_files(self, files, scan_type) -> dict
    流程：
      upsert_scan_status(running=1, total=len(files), scan_type=scan_type)
      遍历 files：
        parse_file(f) → None 则写 scan_errors，errors+1
        成功则补充：
          record["log_path"]   = str(f)
          record["win_path"]   = make_win_path(f)
          record["source"]     = get_source(f)
          record["indexed_at"] = datetime.now().isoformat()
        insert_record() → True inserted+1，False skipped+1
        每 500 条更新一次 scan_status.done
      upsert_scan_status(running=0, done=total)
      返回 {total, inserted, skipped, errors}

  def run_full(self) -> dict
    collect_all() → _process_files("full")

  def run_poll(self) -> dict
    collect_incremental() → _process_files("poll")

CLI 入口（if __name__ == "__main__"）：
  --config  默认 /opt/monitorcenter/config/wipe_paths.json
  --full    有则 run_full()，无则 run_poll()
  每 500 条打印进度
  最终打印汇总

验收：
  # 小范围测试（先用100个文件）
  python3 -m modules.wipe.scanner --config config/wipe_paths.json --full
  sqlite3 data/wipe_index.db "SELECT COUNT(*) FROM wipe_records;"
  sqlite3 data/wipe_index.db "SELECT source, COUNT(*) FROM wipe_records GROUP BY source;"
  sqlite3 data/wipe_index.db "SELECT * FROM scan_errors LIMIT 5;"