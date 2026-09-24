from pathlib import Path

from modules.mem.parser import parse_file, compute_module_statuses

LOG_DIR = Path(r"..\Mem\test_log")

WITH_ERROR = "3 10 2025-74E07175-MemTest86-Report-20250314-142914_979757.html"
NO_ERROR = "3 10 2025-74E07175-MemTest86-Report-20250314-151344_161697.html"

ok = True


def check(label, cond):
    global ok
    status = "OK" if cond else "FAIL"
    if not cond:
        ok = False
    print(f"  [{status}] {label}")


r1 = parse_file(LOG_DIR / WITH_ERROR)
r2 = parse_file(LOG_DIR / NO_ERROR)

print(f"=== {WITH_ERROR} ===")
check("8 modules parsed", len(r1["modules"]) == 8)
check("0 modules_failed", len(r1["modules_failed"]) == 0)
check("ecc_ce == 1", r1["ecc_ce"] == 1)
check("ecc_ue == 0", r1["ecc_ue"] == 0)
check("1 error line parsed", len(r1["errors"]) == 1 and r1["errors"][0]["parse_ok"] == 1)
check("error attributed to 35BA48C9", r1["errors"][0]["module_sn"] == "35BA48C9")
check("unparsed_error_lines == 0", r1["unparsed_error_lines"] == 0)
check("test_start == 2025-03-14 14:29:14", r1["test_start"] == "2025-03-14 14:29:14")
check("overall_result == PASS", r1["overall_result"] == "PASS")
check("system_sn == S16580317A07443", r1["system_sn"] == "S16580317A07443")
check("parse_ok True", r1["parse_ok"] is True)

statuses1, unattr1 = compute_module_statuses(r1)
check("35BA48C9 status == WARN", statuses1.get("35BA48C9", {}).get("status") == "WARN")
other_sns = [m["module_sn"] for m in r1["modules"] if m["module_sn"] != "35BA48C9"]
check("other 7 modules PASS", all(statuses1[sn]["status"] == "PASS" for sn in other_sns) and len(other_sns) == 7)
check("has_unattributed_errors False", unattr1 is False)

print(f"\n=== {NO_ERROR} ===")
check("8 modules parsed", len(r2["modules"]) == 8)
check("ecc_ce == 0 (no ECC rows present)", r2["ecc_ce"] == 0)
check("ecc_ue == 0", r2["ecc_ue"] == 0)
check("0 errors", len(r2["errors"]) == 0)
check("test_start == 2025-03-14 15:13:44", r2["test_start"] == "2025-03-14 15:13:44")

statuses2, unattr2 = compute_module_statuses(r2)
check("all 8 modules PASS", all(s["status"] == "PASS" for s in statuses2.values()) and len(statuses2) == 8)
check("has_unattributed_errors False", unattr2 is False)

print("\n=== cross-report checks ===")
sns1 = {m["module_sn"] for m in r1["modules"]}
sns2 = {m["module_sn"] for m in r2["modules"]}
check("same 8 SNs in both reports", sns1 == sns2)
check("report_uid differs (different test_start)", r1["report_uid"] != r2["report_uid"])
check("file_sha256 differs", r1["file_sha256"] != r2["file_sha256"])

print("\nDIMM sample (A1):")
a1 = next(m for m in r1["modules"] if m["dimm_slot"] == "A1")
print(f"  {a1}")
check("A1 size_gb == 64", a1["size_gb"] == 64)
check("A1 mem_type == DDR4", a1["mem_type"] == "DDR4")
check("A1 rank_org == 4Rx8", a1["rank_org"] == "4Rx8")
check("A1 is_ecc == 1", a1["is_ecc"] == 1)
check("A1 pc_class == PC4-19200", a1["pc_class"] == "PC4-19200")
check("A1 vendor == Samsung", a1["vendor"] == "Samsung")
check("A1 part_number == M386A8K40BM1-CRC", a1["part_number"] == "M386A8K40BM1-CRC")
check("A1 module_sn == 74E07175", a1["module_sn"] == "74E07175")
check("A1 smbios_profile == 2400MT/s", a1["smbios_profile"] == "2400MT/s")

print(f"\nspd_map size: {len(r1['spd_map'])}")
check("spd_map has 8 entries", len(r1["spd_map"]) == 8)
check("spd_map 74E07175 -> channel 0, slot 0", r1["spd_map"].get("74E07175") == {"channel": 0, "slot": 0})

print(f"\ntests parsed: {len(r1['tests'])}")
check("2 test rows parsed", len(r1["tests"]) == 2)

print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
