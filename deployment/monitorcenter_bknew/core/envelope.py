"""Standard envelope builder used by all modules."""


def build_envelope(module_name, sn, timestamp, overall_result,
                   summary, hostname, payload):
    """Build a standard test report envelope.

    Args:
        module_name: Short name of the test module (e.g. "laptop", "ram").
        sn: Device serial number used as primary identifier.
        timestamp: ISO 8601 timestamp string of when the test ran.
        overall_result: "PASS" or "FAIL".
        summary: Short human-readable summary string.
        hostname: Hostname of the machine that ran the test.
        payload: Original module-specific payload (dict).

    Returns:
        dict: Envelope ready to persist as JSON.
    """
    return {
        "module": module_name,
        "sn": sn,
        "timestamp": timestamp,
        "overall_result": overall_result,
        "summary": summary,
        "hostname": hostname,
        "payload": payload,
    }
