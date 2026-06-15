import os
import re
from datetime import datetime
from pathlib import Path


def _search(pattern, text, group=1, flags=0):
    m = re.search(pattern, text, flags)
    if not m:
        return None
    val = m.group(group).strip()
    return val if val else None


def _to_float(s):
    try:
        return float(s) if s is not None else None
    except ValueError:
        return None


def _to_int(s):
    try:
        return int(s) if s is not None else None
    except ValueError:
        return None


def _parse_ipdt_datetime(s):
    """Parse IPDT time string like '1/2/2026 12:09:03 PM' → ISO string."""
    if not s:
        return None
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt).isoformat()
        except ValueError:
            continue
    return None


def _find_image(dir_path):
    """Return absolute path to first .png or .jpg in dir_path, or None."""
    try:
        for name in os.listdir(dir_path):
            if name.lower().endswith((".png", ".jpg", ".jpeg")):
                return os.path.join(dir_path, name)
    except OSError:
        pass
    return None


def _parse_cpu_series(processor_name: str, cpu_family: str | None) -> str:
    if not processor_name:
        return "Other"
    pn = processor_name
    if "Xeon" in pn:
        if "Platinum" in pn:
            return "Xeon Platinum"
        if "Gold" in pn:
            return "Xeon Gold"
        if "Silver" in pn:
            return "Xeon Silver"
        if "Bronze" in pn:
            return "Xeon Bronze"
        if re.search(r"Xeon\s+E7", pn):
            return "Xeon E7"
        if re.search(r"Xeon\s+E5", pn):
            return "Xeon E5"
        if re.search(r"Xeon\s+E3", pn):
            return "Xeon E3"
        return "Xeon Other"
    if cpu_family:
        return f"Core {cpu_family}"   # "Core i3", "Core i5", etc.
    return "Other"


def _parse_processor_name(processor_name):
    """
    Extract manufacturer, family, model, generation, full_name, speed_ghz
    from a string like 'Intel(R) Core(TM) i5-8500 CPU @ 3.00GHz'.
    """
    if not processor_name:
        return None, None, None, None, None, None

    manufacturer = None
    if "Intel" in processor_name:
        manufacturer = "Intel"
    elif "AMD" in processor_name:
        manufacturer = "AMD"

    # family + model: match i3-8100, i5-8500, i7-9700, i9-9900, etc.
    m = re.search(r"\b(i[3579])-(\d{4,5}[A-Z]*)", processor_name, re.IGNORECASE)
    if m:
        cpu_family = m.group(1).lower()        # i5
        cpu_model_str = m.group(2).upper()     # 8500
        cpu_full_name = f"{cpu_family}-{cpu_model_str}"  # i5-8500
        # generation = leading digit(s) before the last 3 digits
        digits = re.match(r"(\d+)", cpu_model_str)
        if digits:
            model_num = digits.group(1)
            # 4-digit model: gen = first digit; 5-digit: gen = first two
            cpu_generation = int(model_num[:-3]) if len(model_num) > 3 else int(model_num[0])
        else:
            cpu_generation = None
    else:
        cpu_family = None
        cpu_model_str = None
        cpu_full_name = None
        cpu_generation = None

    # speed: '@ 3.00GHz'
    m_spd = re.search(r"@\s*([\d.]+)\s*GHz", processor_name, re.IGNORECASE)
    speed_ghz = _to_float(m_spd.group(1)) if m_spd else None

    return manufacturer, cpu_family, cpu_model_str, cpu_generation, cpu_full_name, speed_ghz


def parse_log(log_path: str) -> dict | None:
    """
    Parse a single TESTRESULTS.TXT file.
    Returns a dict of extracted fields, or None if the file is unreadable/invalid.
    """
    log_path = os.path.abspath(log_path)
    dir_path = os.path.dirname(log_path)
    sn = os.path.basename(dir_path)

    # Read file with utf-8 fallback to latin-1
    try:
        try:
            with open(log_path, encoding="utf-8") as f:
                text = f.read()
        except UnicodeDecodeError:
            with open(log_path, encoding="latin-1") as f:
                text = f.read()
    except OSError:
        return None

    # Validate it's an IPDT log
    if "IPDT64" not in text:
        return None

    # --- Top-level result ---
    ipdt_revision = _search(r"IPDT64 - Revision:\s*(.+)", text)
    start_str = _search(r"IPDT64 - Start Time:\s*(.+)", text)
    end_str = _search(r"IPDT64 - End Time:\s*(.+)", text)
    raw_result = _search(r"IPDT64 - Result:\s*(\w+)", text)
    overall_result = raw_result.capitalize() if raw_result else None  # "Pass" or "Fail"

    start_iso = _parse_ipdt_datetime(start_str)
    end_iso = _parse_ipdt_datetime(end_str)

    duration_sec = None
    if start_iso and end_iso:
        try:
            dt_start = datetime.fromisoformat(start_iso)
            dt_end = datetime.fromisoformat(end_iso)
            duration_sec = int((dt_end - dt_start).total_seconds())
        except ValueError:
            pass

    test_date = start_iso[:10] if start_iso else None

    # --- Processor name (from BrandString section or System Info) ---
    # Prefer System Info block for consistency
    processor_name = _search(r"^Processor Name:\s*(.+)", text, flags=re.MULTILINE)
    if not processor_name:
        # Fallback: BrandString test "Detected: Intel(R) Core..."
        processor_name = _search(r"Detected:\s*(Intel\(R\).+GHz)", text)

    manufacturer, cpu_family, cpu_model, cpu_generation, cpu_full_name, speed_ghz = \
        _parse_processor_name(processor_name)
    cpu_series = _parse_cpu_series(processor_name, cpu_family)

    # --- System Information block ---
    physical_cores = _to_int(_search(r"Number of Physical Cores:\s*(\d+)", text))
    logical_cores = _to_int(_search(r"Number of Logical Cores:\s*(\d+)", text))
    os_info = _search(r"Operating System:\s*(.+)", text)
    graphics_info = _search(r"Graphics Information:\s*(.+)", text)

    # --- Cache Test ---
    l3_cache_kb = _to_int(_search(r"Detected L3 Cache Size\s*-->\s*(\d+)", text))

    # --- IMC Test: memory size ---
    m_mem = re.search(r"Detected Memory Size is\s*-->\s*([\d.]+)\s*GB", text, re.IGNORECASE)
    memory_gb = _to_float(m_mem.group(1)) if m_mem else None

    # --- Frequency Check ---
    expected_freq_ghz = _to_float(_search(r"Expected Processor Frequency:\s*([\d.]+)", text))
    measured_freq_ghz = _to_float(_search(r"Measured Processor Frequency:\s*([\d.]+)", text))

    freq_ratio = None
    if expected_freq_ghz and measured_freq_ghz and expected_freq_ghz > 0:
        freq_ratio = round(measured_freq_ghz / expected_freq_ghz, 4)

    # --- Fail module: find section with 'Test Result - FAIL' ---
    fail_module = None
    if overall_result == "Fail":
        # Each section starts with "CPU1\n<Module Name>\n"
        # Find which module block contains "Test Result - FAIL"
        blocks = re.split(r"-{40,}", text)
        for block in blocks:
            if re.search(r"Test Result\s*-\s*FAIL", block, re.IGNORECASE):
                # Extract module name: second non-empty line after "CPU1"
                lines = [l.strip() for l in block.splitlines() if l.strip()]
                for i, line in enumerate(lines):
                    if line.upper().startswith("CPU"):
                        if i + 1 < len(lines):
                            fail_module = lines[i + 1]
                            break
                if fail_module:
                    break

    # --- Prime Ops: take max across all occurrences ---
    prime_ops_all = [_to_int(v) for v in re.findall(r"Operation Per Second:\s*(\d+)", text)]
    prime_ops_all = [v for v in prime_ops_all if v is not None]
    prime_ops_per_sec = max(prime_ops_all) if prime_ops_all else None

    # --- MFLOPS: take max across all occurrences ---
    mflops_all = [_to_float(v) for v in re.findall(
        r"Million Floating Points per Second,\s*MFLOPS:\s*([\d.]+)", text)]
    mflops_all = [v for v in mflops_all if v is not None]
    # Exclude the very small parallel stress values (< 1.0) by taking the standalone max
    # If all are < 1.0, still return the max
    significant = [v for v in mflops_all if v >= 1.0]
    mflops = max(significant) if significant else (max(mflops_all) if mflops_all else None)

    # --- Image ---
    image_path = _find_image(dir_path)

    return {
        "sn":               sn,
        "log_path":         log_path,
        "image_path":       image_path,
        "manufacturer":     manufacturer,
        "cpu_series":       cpu_series,
        "cpu_family":       cpu_family,
        "cpu_model":        cpu_model,
        "cpu_generation":   cpu_generation,
        "cpu_full_name":    cpu_full_name,
        "processor_name":   processor_name,
        "speed_ghz":        speed_ghz,
        "physical_cores":   physical_cores,
        "logical_cores":    logical_cores,
        "l3_cache_kb":      l3_cache_kb,
        "memory_gb":        memory_gb,
        "expected_freq_ghz": expected_freq_ghz,
        "measured_freq_ghz": measured_freq_ghz,
        "freq_ratio":       freq_ratio,
        "prime_ops_per_sec": prime_ops_per_sec,
        "mflops":           mflops,
        "overall_result":   overall_result,
        "fail_module":      fail_module,
        "test_date":        test_date,
        "start_time":       start_iso,
        "end_time":         end_iso,
        "duration_sec":     duration_sec,
        "ipdt_revision":    ipdt_revision,
        "os_info":          os_info,
        "graphics_info":    graphics_info,
    }
