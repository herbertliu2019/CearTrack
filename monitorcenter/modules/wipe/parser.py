import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


def _search(pattern, text, group=1, flags=0):
    m = re.search(pattern, text, flags)
    if not m:
        return None
    val = m.group(group).strip()
    return val if val else None


def _full_sn_from_sysinfo(log_path: Path, text: str, short_sn: str | None) -> str | None:
    """XERASwin truncates NVMe-behind-SCSI serials to 8 chars in the .log
    ("S3VENY0K"); the companion sysinfo_<SYS>.xml (named on the
    "System Info File" line) has <Storage><SerialNumber>S3VENY0K</...>
    <SerialNumber_Alt>S3VENY0K123456</...>. Return the Alt serial of the
    matching <Storage>, or None if not found / not readable."""
    if not short_sn:
        return None
    name = _search(r"System Info File\s*:\s*(\S+\.xml)", text)
    if not name:
        return None
    for d in (log_path.parent, log_path.parent.parent):
        xml_path = d / name
        try:
            if not xml_path.is_file():
                continue
            root = ET.fromstring(xml_path.read_bytes())
        except (OSError, ET.ParseError):
            continue
        cands = []
        for st in root.iter("Storage"):
            sn  = (st.findtext("SerialNumber") or "").strip()
            alt = (st.findtext("SerialNumber_Alt") or "").strip()
            if sn == short_sn and alt and alt != sn:
                cands.append(st)
        # Same-batch drives share the 8-char prefix — narrow by other drive
        # fields the .log and XML both carry; never guess if still ambiguous.
        for log_pat, xml_tag in (
            (r"^\s{4}Max LBA\s*:\s*(\S+)",   "MaxLBA"),
            (r"^\s{4}Capacity\s*:\s*(\S+)",  "Size"),
            (r"^\s{4}Microcode\s*:\s*(\S+)", "Code"),
        ):
            if len(cands) <= 1:
                break
            log_val = _search(log_pat, text, flags=re.MULTILINE)
            if not log_val:
                continue
            cands = [st for st in cands
                     if (st.findtext(xml_tag) or "").strip().upper() == log_val.upper()]
        if len(cands) == 1:
            return cands[0].findtext("SerialNumber_Alt").strip()
        return None
    return None


def parse_log(log_path: Path) -> dict | None:
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    if not re.search(r"Erasure Results", text):
        return None

    # result: regex captures "Passed" or "Failed" → uppercase to "PASSED"/"FAILED"
    raw_result = _search(r"Erasure Results\s*:.+(Passed|Failed)!", text)
    result = raw_result.upper() if raw_result else None

    # wipe date + time
    m_dt = re.search(
        r"Data Erasure Started\s+(\d{2}/\d{2}/\d{4})\s+at\s+(\d{2}:\d{2}:\d{2})", text
    )
    wipe_date = None
    wipe_datetime = None
    if m_dt:
        date_str, time_str = m_dt.group(1), m_dt.group(2)
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%m/%d/%Y %H:%M:%S")
            wipe_date = dt.strftime("%Y-%m-%d")
            wipe_datetime = dt.isoformat()
        except ValueError:
            pass

    # duration — "in X hrs Y.Z min"
    duration_min = None
    m_dur = re.search(r"in\s+(\d+)\s+hrs\s+([\d.]+)\s+min", text)
    if m_dur:
        try:
            duration_min = int(m_dur.group(1)) * 60 + float(m_dur.group(2))
        except ValueError:
            pass

    # protocol: ATA drive → "ATA 8", SCSI drive → "SCSI 6"
    protocol = None
    ata = _search(r"^\s{4}ATA Version\s*:\s*(.+)", text, flags=re.MULTILINE)
    if ata:
        protocol = f"ATA {ata}"
    else:
        scsi = _search(r"^\s{4}SCSI Version\s*:\s*(.+)", text, flags=re.MULTILINE)
        if scsi:
            protocol = f"SCSI {scsi}"

    # log hash — "Certification Hash2 :  32337a92 53b01804 ..."
    log_hash = _search(r"Certification Hash\w*\s*:\s+([0-9a-f ]+)", text)
    if log_hash:
        log_hash = log_hash.strip()

    # numeric helpers
    def to_float(s):
        try:
            return float(s) if s is not None else None
        except ValueError:
            return None

    def to_int(s):
        try:
            return int(s) if s is not None else None
        except ValueError:
            return None

    drive_sn = _search(r"^\s{4}Serial Number\s*:\s*(\S+)", text, flags=re.MULTILINE)
    drive_sn = _full_sn_from_sysinfo(log_path, text, drive_sn) or drive_sn

    return {
        "drive_sn":         drive_sn,
        "system_sn":        _search(r"System Serial Number\s*:\s*(\S+)", text),
        "wipe_date":        wipe_date,
        "wipe_datetime":    wipe_datetime,
        "duration_min":     duration_min,
        "method":           _search(r"^\s{4}Method\s*:\s*(.+)", text, flags=re.MULTILINE),
        "result":           result,
        "health_score":     to_float(_search(r"^\s{4}Health Score\s*:\s*([\d.]+)", text, flags=re.MULTILINE)),
        "grade":            _search(r"^\s{4}Grade\s*:\s*(GRADE\s+\w+)", text, flags=re.MULTILINE),
        "ssd_life":         to_int(_search(r"^\s{4}SSD Life\s*:\s*(\d+)", text, flags=re.MULTILINE)),
        "power_on_hrs":     to_int(_search(r"^\s{4}Power on Hrs\s*:\s*(\d+)", text, flags=re.MULTILINE)),
        "manufacturer":     _search(r"^\s{4}Manufacturer\s*:\s*(.+)", text, flags=re.MULTILINE),
        "drive_model":      _search(r"^\s{4}Model\s*:\s*(.+)", text, flags=re.MULTILINE),
        "capacity":         _search(r"^\s{4}Capacity\s*:\s*(.+)", text, flags=re.MULTILINE),
        "device_type":      _search(r"^\s{4}Device Type\s*:\s*(.+)", text, flags=re.MULTILINE),
        "sys_manufacturer": _search(r"System Manufacturer\s*:\s*(.+)", text),
        "sys_model":        _search(r"System Model\s*:\s*(.+)", text),
        "sys_chassis":      _search(r"System Chassis Type\s*:\s*(.+)", text),
        # — new fields —
        "firmware":         _search(r"^\s{4}Microcode\s*:\s*(\S+)", text, flags=re.MULTILINE),
        "protocol":         protocol,
        "software_version": _search(r"XERASwin\s+(v[\d.]+\w*)", text),
        "log_hash":         log_hash,
        "location1":        _search(r"^\s+Location 1\s*:[ \t]*([^\n]+)", text, flags=re.MULTILINE),
        "location2":        _search(r"^\s+Location 2\s*:[ \t]*([^\n]+)", text, flags=re.MULTILINE),
        "erasure_rule":     _search(r"^\s{4}Rule\s*:\s*(.+)", text, flags=re.MULTILINE),
        "failure_reason":   _search(r"Failure Reason\s*:\s*(.+)", text),
    }
