TASK-03｜scanner.py

文件：/opt/monitorcenter/modules/wipe/scanner.py

实现两种扫描模式：全量扫描 + 当月轮询。

MONTH_DIRS 常量（模块级）：
{
  1:"01 January", 2:"02 February", 3:"03 March",
  4:"04 April",   5:"05 May",      6:"06 June",
  7:"07 July",    8:"08 August",   9:"09 September",
  10:"10 October",11:"11 November",12:"12 December"
}

class WipeScanner:
    def __init__(self, log_root: str, db_path: str, win_share_root: str)

    def make_win_path(self, log_path: Path) -> str
      规则见 skill.md win_path 生成规则

    def collect_all(self) -> list[Path]
      遍历 log_root/logs/YYYY/MM MonthName/*.log
      YYYY：目录名为纯4位数字
      月份：目录名匹配 MONTH_DIRS 中的值
      返回全部 .log 文件路径

    def collect_current_month(self) -> list[Path]
      只扫 log_root/logs/当前年/当前月目录/
      使用 datetime.now() 确定年月
      目录不存在时返回空列表

    def _process_files(self, files: list[Path],
                       scan_type: str) -> dict
      私有方法，供 run_full() 和 run_poll() 调用
      流程：
        1. upsert_scan_status(running=1, total=len(files),
                              done=0, scan_type=scan_type)
        2. 遍历 files：
           - 已在 DB（insert_record 返回 False）→ skipped+1
           - parse 返回 None → 写 scan_errors，errors+1
           - 成功 → record['log_path']=str(f)
                     record['win_path']=make_win_path(f)
                     record['indexed_at']=now
                     insert_record() → inserted+1
           - 每 100 条更新一次 scan_status.done
        3. upsert_scan_status(running=0, done=total)
        4. 返回 {"total":N,"inserted":N,"skipped":N,"errors":N}

    def run_full(self) -> dict
      collect_all() → _process_files(..., "full")

    def run_poll(self) -> dict
      collect_current_month() → _process_files(..., "poll")

CLI 入口（if __name__ == "__main__"）：
  --config  路径，默认 /opt/monitorcenter/config/wipe_paths.json
  --full    flag，有则 run_full()，无则 run_poll()
  每扫描 500 个文件打印一次进度
  最终打印汇总结果

验收：
# 先用少量测试文件验证
python3 -m modules.wipe.scanner --config config/wipe_paths.json --full
# 输出示例：
# Scanning: 500/30000...
# Scanning: 1000/30000...
# Done: total=30000 inserted=30000 skipped=0 errors=0