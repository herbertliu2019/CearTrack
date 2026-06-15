"""
parser_makor.py — Blancco / Makor EDE XML report parser

Typical structure:
  <ErasureReport>
    <ErasureResults>
      <ErasureResult>PASS</ErasureResult>
      <ErasureDate>01/15/2024</ErasureDate>
      <ErasureTime>14:30:00</ErasureTime>
      <ErasureDuration>45:30</ErasureDuration>   # MM:SS
      <ErasureMethod>...</ErasureMethod>
      <ErasureRule>...</ErasureRule>
      <FailureReason>...</FailureReason>
    </ErasureResults>
    <HardDriveInfo>
      <SerialNumber>...</SerialNumber>
      <Model>...</Model>
      <Capacity>...</Capacity>
      <Manufacturer>...</Manufacturer>
      <DeviceType>...</DeviceType>
      <Firmware>...</Firmware>
      <HealthScore>...</HealthScore>
      <Grade>...</Grade>
      <PowerOnHours>...</PowerOnHours>
    </HardDriveInfo>
    <SystemInfo>
      <SystemSerialNumber>...</SystemSerialNumber>
      <SystemManufacturer>...</SystemManufacturer>
      <SystemModel>...</SystemModel>
      <SystemChassisType>...</SystemChassisType>
    </SystemInfo>
    <SoftwareInfo>
      <SoftwareVersion>...</SoftwareVersion>
    </SoftwareInfo>
  </ErasureReport>
"""

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


def _find(root: ET.Element, *tags: str):
    """Try multiple tag names; return stripped text of first match or None."""
    for tag in tags:
        el = root.find(".//" + tag)
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
    return None


def _parse_date(s: str | None) -> str | None:
    """MM/DD/YYYY → YYYY-MM-DD. Returns None on failure."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        try:
            return datetime.strptime(s.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            return None


def _parse_duration(s: str | None) -> float | None:
    """
    ErasureDuration is 'MM:SS'.
    Returns total minutes as float, or None on failure.
    """
    if not s:
        return None
    try:
        parts = s.strip().split(":")
        if len(parts) == 2:
            return int(parts[0]) + int(parts[1]) / 60
        if len(parts) == 3:
            # HH:MM:SS — convert to minutes
            return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60
    except (ValueError, IndexError):
        pass
    return None


def _to_float(s: str | None) -> float | None:
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _to_int(s: str | None) -> int | None:
    try:
        return int(s) if s else None
    except ValueError:
        return None


def parse_makor_xml(xml_path: Path) -> dict | None:
    """
    Parse a Blancco / Makor EDE XML report.
    Returns a dict with normalized wipe record fields, or None if invalid.
    """
    try:
        tree = ET.parse(str(xml_path))
        root = tree.getroot()
    except ET.ParseError:
        return None
    except OSError:
        return None

    # Must have ErasureResults node
    er = root.find(".//ErasureResults")
    if er is None:
        er = root.find(".//ErasureResult")
        if er is None:
            return None

    # ── Result ────────────────────────────────────────────────────
    raw_result = _find(root, "ErasureResult", "Result", "ErasureStatus")
    if raw_result:
        r = raw_result.upper()
        result = "PASSED" if r in ("PASS", "PASSED", "SUCCESS") else (
                 "FAILED"  if r in ("FAIL", "FAILED", "ERROR")  else raw_result.upper())
    else:
        result = None

    # ── Dates / times ─────────────────────────────────────────────
    raw_date = _find(root, "ErasureDate", "Date", "StartDate")
    wipe_date = _parse_date(raw_date)

    raw_time = _find(root, "ErasureTime", "StartTime", "Time")
    wipe_datetime = None
    if wipe_date and raw_time:
        try:
            wipe_datetime = f"{wipe_date}T{raw_time.split('.')[0]}"
        except Exception:
            pass

    # ── Duration ─────────────────────────────────────────────────
    duration_min = _parse_duration(_find(root, "ErasureDuration", "Duration"))

    # ── Drive info ────────────────────────────────────────────────
    drive_sn     = _find(root, "SerialNumber", "DriveSerial", "HddSerial", "Serial")
    manufacturer = _find(root, "Manufacturer", "DriveManufacturer", "HddManufacturer")
    drive_model  = _find(root, "Model", "DriveModel", "HddModel")
    capacity     = _find(root, "Capacity", "DriveCapacity", "Size")
    device_type  = _find(root, "DeviceType", "DriveType", "HddType")
    firmware     = _find(root, "Firmware", "FirmwareVersion", "Microcode")
    health_score = _to_float(_find(root, "HealthScore", "Health", "SmartScore"))
    grade        = _find(root, "Grade")
    power_on_hrs = _to_int(_find(root, "PowerOnHours", "PowerOnHrs", "POH"))

    # ── System info ───────────────────────────────────────────────
    system_sn        = _find(root, "SystemSerialNumber", "SystemSerial", "ComputerSerial")
    sys_manufacturer = _find(root, "SystemManufacturer", "ComputerManufacturer")
    sys_model        = _find(root, "SystemModel", "ComputerModel")
    sys_chassis      = _find(root, "SystemChassisType", "ChassisType")

    # ── Erasure method / rule ────────────────────────────────────
    method       = _find(root, "ErasureMethod", "ErasureStandard", "Method", "Standard")
    erasure_rule = _find(root, "ErasureRule", "Rule")
    failure_reason = _find(root, "FailureReason", "ErrorMessage", "FailReason")

    # ── Software / hash / location ───────────────────────────────
    software_version = _find(root, "SoftwareVersion", "AppVersion", "Version")
    log_hash         = _find(root, "ReportHash", "Hash", "CertificationHash")
    location1        = _find(root, "Location1", "Location", "Slot")
    location2        = _find(root, "Location2")

    return {
        "drive_sn":         drive_sn,
        "system_sn":        system_sn,
        "wipe_date":        wipe_date,
        "wipe_datetime":    wipe_datetime,
        "duration_min":     duration_min,
        "method":           method,
        "result":           result,
        "health_score":     health_score,
        "grade":            grade,
        "ssd_life":         None,          # EDE XML has no SSD life field
        "power_on_hrs":     power_on_hrs,
        "manufacturer":     manufacturer,
        "drive_model":      drive_model,
        "capacity":         capacity,
        "device_type":      device_type,
        "sys_manufacturer": sys_manufacturer,
        "sys_model":        sys_model,
        "sys_chassis":      sys_chassis,
        "firmware":         firmware,
        "protocol":         None,
        "software_version": software_version,
        "log_hash":         log_hash,
        "location1":        location1,
        "location2":        location2,
        "erasure_rule":     erasure_rule,
        "failure_reason":   failure_reason,
    }
