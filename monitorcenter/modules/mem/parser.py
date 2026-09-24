"""MemTest86 HTML report parser.

Parses a MemTest86 "Certificate report" HTML export into a structured
dict: report-level fields, per-DIMM specs, per-test rows, and per-error
rows.

Two things make this report format awkward:

1. The file is UTF-16 LE with a BOM, not UTF-8 — must sniff the BOM,
   never assume an encoding.
2. The exported HTML is not well-formed (some <div> sections are opened
   but never explicitly closed), so a real DOM tree can't be trusted for
   nesting. We track "the most recently opened known section div" instead,
   which is robust to the report's fixed, linear section order (header ->
   summary -> sysinfo -> results -> footer) regardless of how the divs
   actually close.

Tolerant by design: a report with no errors omits the ECC-count rows and
the "Last 10 Errors" block entirely (that's normal, not a parse failure),
and an error line in a format we've never seen (real FAIL logs weren't
available when this was written) is never dropped — it's kept verbatim
with parse_ok=0 so nothing silently disappears.
"""

import hashlib
import re
from html.parser import HTMLParser

_SECTION_DIVS = {"header", "summary", "sysinfo", "results", "footer"}

_TEST_ROW_RE = re.compile(r"^Test\s+(\d+)\s*\[")

_ERROR_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*-\s*\[(?P<etype>[^\]]+)\]\s*"
    r"Test:\s*(?P<test_no>\d+),\s*"
    r"\(Channel,Slot,Rank,Bank,Row,Col\):\s*\((?P<csrbrc>[^)]*)\),\s*"
    r"ECC Corrected:\s*(?P<corrected>Yes|No),\s*"
    r"Syndrome:\s*(?P<syndrome>\S+),\s*"
    r"Channel-Slot:\s*(?P<chslot>[\d\-]+)\s*"
    r"\(S/N:\s*(?P<sn>[^)]+)\)"
)
_FALLBACK_SN_RE = re.compile(r"\(S/N:\s*(\w+)\)")
_FALLBACK_CHSLOT_RE = re.compile(r"Channel-Slot:\s*([\d\-]+)")


# ---------------------------------------------------------------------------
# Encoding / hashing helpers
# ---------------------------------------------------------------------------

def read_report_text(path) -> str:
    """Sniff the BOM instead of assuming an encoding (§2.1 of the spec)."""
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8", errors="replace")


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def report_uid(system_sn: str | None, test_start: str | None) -> str:
    """Business primary key for a report — never the filename (§2.3)."""
    key = f"{system_sn or ''}|{test_start or ''}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# HTML -> flat (section, cells) rows
# ---------------------------------------------------------------------------

class _RowExtractor(HTMLParser):
    """Flattens every <tr>...</tr> into (section, [cell_text, ...])."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, list[str]]] = []
        self._section = "header"
        self._in_style = False
        self._in_row = False
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._row_cells: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "style":
            self._in_style = True
        elif tag == "div":
            cls = dict(attrs).get("class", "") or ""
            for name in _SECTION_DIVS:
                if name in cls.split():
                    self._section = name
                    break
        elif tag == "tr":
            self._in_row = True
            self._row_cells = []
        elif tag == "td":
            self._in_cell = True
            self._cell_parts = []
        elif tag == "br" and self._in_cell:
            self._cell_parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False
        elif tag == "td":
            if self._in_cell:
                self._row_cells.append("".join(self._cell_parts).strip())
            self._in_cell = False
        elif tag == "tr":
            if self._in_row and self._row_cells:
                self.rows.append((self._section, self._row_cells))
            self._in_row = False

    def handle_data(self, data):
        if self._in_style:
            return
        if self._in_cell:
            self._cell_parts.append(data)


def extract_rows(html_text: str) -> list[tuple[str, list[str]]]:
    parser = _RowExtractor()
    parser.feed(html_text)
    return parser.rows


# ---------------------------------------------------------------------------
# DIMM spec-string parsing — e.g. "64GB DDR4 4Rx8 ECC PC4-19200"
# ---------------------------------------------------------------------------

def _parse_dimm_spec(slot: str, spec_raw: str) -> dict:
    d = {
        "dimm_slot": slot,
        "spec_raw": spec_raw.strip(),
        "size_gb": None,
        "mem_type": None,
        "rank_org": None,
        "is_ecc": 0,
        "pc_class": None,
        "vendor": None,
        "part_number": None,
        "module_sn": None,
        "smbios_profile": None,
    }
    parts = spec_raw.split()
    if parts:
        m = re.match(r"(\d+)\s*GB", parts[0], re.I)
        if m:
            d["size_gb"] = int(m.group(1))
    if len(parts) > 1:
        d["mem_type"] = parts[1]
    rank_m = re.search(r"\d+Rx\d+", spec_raw)
    if rank_m:
        d["rank_org"] = rank_m.group(0)
    if "ECC" in spec_raw.upper():
        d["is_ecc"] = 1
    pc_m = re.search(r"PC\d+-\d+", spec_raw)
    if pc_m:
        d["pc_class"] = pc_m.group(0)
    return d


# ---------------------------------------------------------------------------
# Error-line parsing (§3.5) — tolerant, never raises
# ---------------------------------------------------------------------------

def _num_or_none(v: str):
    v = v.strip()
    return None if v == "" or v.upper() == "N/A" else int(v)


def _parse_error_line(line: str, result: dict) -> None:
    m = _ERROR_LINE_RE.match(line)
    if m:
        gd = m.groupdict()
        parts = [p.strip() for p in gd["csrbrc"].split(",")]
        channel = slot = rank = bank = row = col = None
        if len(parts) == 6:
            channel, slot, rank, bank, row, col = (_num_or_none(p) for p in parts)
        result["errors"].append({
            "err_time": gd["ts"],
            "err_type": gd["etype"],
            "test_no": int(gd["test_no"]),
            "channel": channel, "slot": slot, "rank": rank,
            "bank": bank, "row": row, "col": col,
            "ecc_corrected": 1 if gd["corrected"] == "Yes" else 0,
            "syndrome": gd["syndrome"],
            "channel_slot": gd["chslot"],
            "module_sn": gd["sn"].strip().upper(),
            "raw_line": line,
            "parse_ok": 1,
        })
        return

    # Unrecognized format (§2.6 — real FAIL lines were never sampled).
    # Weak-extract what we can; never drop the line.
    sn_m = _FALLBACK_SN_RE.search(line)
    chslot_m = _FALLBACK_CHSLOT_RE.search(line)
    result["errors"].append({
        "err_time": None, "err_type": None, "test_no": None,
        "channel": None, "slot": None, "rank": None,
        "bank": None, "row": None, "col": None,
        "ecc_corrected": None,
        "syndrome": None,
        "channel_slot": chslot_m.group(1) if chslot_m else None,
        "module_sn": sn_m.group(1).strip().upper() if sn_m else None,
        "raw_line": line,
        "parse_ok": 0,
    })
    result["unparsed_error_lines"] += 1


def _parse_hms(s: str):
    try:
        parts = [int(p) for p in s.split(":")]
    except ValueError:
        return None
    if len(parts) == 3:
        h, m, sec = parts
    elif len(parts) == 2:
        h, (m, sec) = 0, parts
    else:
        return None
    return h * 3600 + m * 60 + sec


# ---------------------------------------------------------------------------
# "results" section row dispatch
# ---------------------------------------------------------------------------

def _parse_results_row(cells: list[str], result: dict) -> None:
    if len(cells) == 2:
        label, value = cells[0].strip(), cells[1].strip()
        if label == "Test Start Time":
            result["test_start"] = value
        elif label == "Elapsed Time":
            result["elapsed"] = value
        elif label == "Memory Range Tested":
            result["mem_range"] = value
            m = re.search(r"\((\d+)\s*MB\)", value)
            if m:
                result["mem_size_mb"] = int(m.group(1))
        elif label == "CPU Selection Mode":
            result["cpu_sel_mode"] = value
        elif label == "CPU Temperature Min/Max/Ave":
            result["cpu_temp_raw"] = value
            nums = re.findall(r"(\d+)C", value)
            if len(nums) == 3:
                result["cpu_temp_min"], result["cpu_temp_max"], result["cpu_temp_avg"] = (int(n) for n in nums)
        elif label == "Lowest memory speed":
            result["mem_speed_low"] = value
        elif label == "Highest memory speed":
            result["mem_speed_high"] = value
        elif label == "ECC Polling":
            result["ecc_polling"] = value
        elif label == "# Tests Completed":
            result["tests_completed"] = value
            m = re.search(r"\((\d+)%\)", value)
            if m:
                result["tests_completed_pct"] = int(m.group(1))
        elif label == "# Tests Passed":
            result["tests_passed"] = value
        elif label == "ECC Correctable Errors":
            try:
                result["ecc_ce"] = int(value)
            except ValueError:
                pass
        elif label == "ECC Uncorrectable Errors":
            try:
                result["ecc_ue"] = int(value)
            except ValueError:
                pass

    elif len(cells) == 3:
        name, passed_raw, errors_raw = cells[0].strip(), cells[1].strip(), cells[2].strip()
        if _TEST_ROW_RE.match(name):
            m = _TEST_ROW_RE.match(name)
            pct_m = re.search(r"\((\d+)%\)", passed_raw)
            try:
                errors_n = int(errors_raw)
            except ValueError:
                errors_n = None
            result["tests"].append({
                "test_no": int(m.group(1)),
                "test_name": name,
                "passed_raw": passed_raw,
                "passed_pct": int(pct_m.group(1)) if pct_m else None,
                "errors": errors_n,
            })

    elif len(cells) == 1:
        line = cells[0].strip()
        if line and line != "Last 10 Errors":
            _parse_error_line(line, result)


# ---------------------------------------------------------------------------
# Top-level report parse
# ---------------------------------------------------------------------------

def parse_report(html_text: str) -> dict:
    rows = extract_rows(html_text)

    result: dict = {
        "report_date": None, "generated_by": None, "overall_result": None,
        "system_mfr": None, "system_product": None, "system_sn": None,
        "baseboard_mfr": None, "baseboard_product": None, "baseboard_sn": None,
        "cpu_type": None, "ram_config": None,
        "slots_count": None, "modules_count": None,
        "test_start": None, "elapsed": None, "elapsed_sec": None,
        "mem_range": None, "mem_size_mb": None, "cpu_sel_mode": None,
        "cpu_temp_raw": None, "cpu_temp_min": None, "cpu_temp_max": None, "cpu_temp_avg": None,
        "mem_speed_low": None, "mem_speed_high": None, "ecc_polling": None,
        "tests_completed": None, "tests_completed_pct": None, "tests_passed": None,
        "ecc_ce": 0, "ecc_ue": 0,
        "modules": [],
        "modules_failed": [],
        "tests": [],
        "errors": [],
        "spd_map": {},
        "unparsed_error_lines": 0,
        "parse_ok": True,
        "parse_note": None,
    }

    parent = None       # 'system' | 'baseboard' | 'spd' | 'dimm' | None
    cur_dimm = None

    def finalize_dimm():
        nonlocal cur_dimm
        if cur_dimm is None:
            return
        sn = (cur_dimm.get("module_sn") or "").strip().upper()
        if not sn or sn == "N/A" or not cur_dimm.get("vendor"):
            cur_dimm["parse_ok"] = False
            result["modules_failed"].append(cur_dimm)
        else:
            cur_dimm["module_sn"] = sn
            cur_dimm["parse_ok"] = True
            result["modules"].append(cur_dimm)
        cur_dimm = None

    for section, cells in rows:
        if section == "summary":
            if len(cells) < 2:
                continue
            label, value = cells[0].strip(), cells[1].strip()
            if label == "Report Date":
                result["report_date"] = value
            elif label == "Generated by":
                result["generated_by"] = value
            elif label == "Result":
                result["overall_result"] = value

        elif section == "sysinfo":
            if len(cells) < 2:
                continue
            label, value = cells[0].strip(), cells[1].strip()

            if label == "System":
                parent = "system"
            elif label == "Baseboard":
                parent = "baseboard"
            elif label == "BIOS":
                parent = None
            elif label == "CPU Type":
                result["cpu_type"] = value
                parent = None
            elif label == "RAM Configuration":
                result["ram_config"] = value
                parent = None
            elif label == "Number of RAM SPDs detected":
                parent = None
            elif label.startswith("SPD #"):
                parent = "spd"
            elif label == "Number of RAM slots":
                try:
                    result["slots_count"] = int(value)
                except ValueError:
                    pass
                parent = None
            elif label == "Number of RAM modules":
                try:
                    result["modules_count"] = int(value)
                except ValueError:
                    pass
                parent = None
            elif label.startswith("DIMM "):
                finalize_dimm()
                slot = label.split(" ", 1)[1].strip()
                cur_dimm = _parse_dimm_spec(slot, value)
                parent = "dimm"
            elif parent == "dimm" and cur_dimm is not None:
                if label == "Vendor Part Info":
                    parts = [p.strip() for p in value.split(" / ")]
                    cur_dimm["vendor"] = parts[0] if len(parts) > 0 else None
                    cur_dimm["part_number"] = parts[1] if len(parts) > 1 else None
                    cur_dimm["module_sn"] = parts[2] if len(parts) > 2 else None
                elif label == "SMBIOS Profile":
                    cur_dimm["smbios_profile"] = value.strip()
            elif parent == "spd":
                if label == "Vendor Part Info":
                    parts = [p.strip() for p in value.split(" / ")]
                    if len(parts) >= 3:
                        sn = parts[2].strip().upper()
                        chm = re.search(r"Channel:\s*(\d+)\s*Slot:\s*(\d+)", value)
                        if chm:
                            result["spd_map"][sn] = {
                                "channel": int(chm.group(1)),
                                "slot": int(chm.group(2)),
                            }
            elif parent in ("system", "baseboard"):
                if label == "Manufacturer":
                    result[f"{parent}_mfr"] = value
                elif label == "Product Name":
                    result[f"{parent}_product"] = value
                elif label == "Serial Number":
                    result[f"{parent}_sn"] = value

        elif section == "results":
            _parse_results_row(cells, result)

    finalize_dimm()

    if result["elapsed"]:
        result["elapsed_sec"] = _parse_hms(result["elapsed"])

    found = len(result["modules"]) + len(result["modules_failed"])
    if result["modules_count"] and found != result["modules_count"]:
        result["parse_note"] = f"expected {result['modules_count']} modules, found {found}"

    result["parse_ok"] = bool(result["modules"])
    return result


def parse_file(path) -> dict:
    """Parse a MemTest86 report file end to end, including hashes/uid."""
    text = read_report_text(path)
    result = parse_report(text)
    result["file_sha256"] = file_sha256(path)
    result["report_uid"] = report_uid(result.get("system_sn"), result.get("test_start"))
    return result


# ---------------------------------------------------------------------------
# Module-status computation (§4 of the spec) — one report at a time.
# Aggregation across reports (current_status/ever_fail/ever_warn) lives in
# db.py, since it needs the full test-history for a SN, not just one report.
# ---------------------------------------------------------------------------

def compute_module_statuses(parsed: dict) -> tuple[dict[str, dict], bool]:
    """Returns ({module_sn: {status, err_total, err_ecc_ce, err_ecc_ue}}, has_unattributed_errors)."""
    sns = [m["module_sn"] for m in parsed["modules"]]
    overall = (parsed.get("overall_result") or "").upper()
    per_sn = {sn: {"status": "PASS", "err_total": 0, "err_ecc_ce": 0, "err_ecc_ue": 0} for sn in sns}

    attributed_any = False
    for err in parsed["errors"]:
        sn = err.get("module_sn")
        if sn and sn in per_sn:
            attributed_any = True
            per_sn[sn]["err_total"] += 1
            corrected = err.get("ecc_corrected")
            if corrected == 1:
                per_sn[sn]["err_ecc_ce"] += 1
                if per_sn[sn]["status"] != "FAIL":
                    per_sn[sn]["status"] = "WARN"
            else:
                # corrected == 0 (uncorrectable) or None (unknown/fallback-parsed
                # line) — both treated as FAIL; we never let an unrecognized
                # error line quietly pass as WARN/PASS.
                per_sn[sn]["err_ecc_ue"] += 1
                per_sn[sn]["status"] = "FAIL"

    has_unattributed = False
    if overall == "FAIL":
        unattributed_on_fail = (not parsed["errors"]) or any(
            not (e.get("module_sn") in per_sn) for e in parsed["errors"]
        )
        if unattributed_on_fail:
            for sn in per_sn:
                per_sn[sn]["status"] = "SUSPECT"
    else:
        if parsed.get("ecc_ce", 0) and not attributed_any:
            has_unattributed = True

    return per_sn, has_unattributed


if __name__ == "__main__":
    import json
    import sys

    for p in sys.argv[1:]:
        r = parse_file(p)
        print(f"=== {p} ===")
        print(json.dumps(r, indent=2, ensure_ascii=False))
        print()
