"""WeasyPrint PDF generator for GPU test reports."""

import os
from pathlib import Path


def generate_pdf(sn: str, envelope: dict) -> str:
    """Generate GPU test report PDF. Returns saved path. Raises on failure."""
    from weasyprint import HTML
    from flask import render_template_string, current_app

    pdf_dir = Path(current_app.config.get("GPU_PDF_DIR",
                                           str(Path(__file__).parent.parent.parent / "data" / "gpu" / "pdf")))
    pdf_dir.mkdir(parents=True, exist_ok=True)

    tpl_path = Path(__file__).parent / "templates" / "gpu" / "gpu_report.html"
    template_str = tpl_path.read_text(encoding="utf-8")

    html_str = render_template_string(
        template_str,
        sn=sn,
        data=envelope.get("payload", {}),
        test_time=envelope.get("timestamp", ""),
        overall=envelope.get("overall_result", "UNKNOWN"),
        hostname=envelope.get("hostname", ""),
    )

    pdf_path = pdf_dir / f"{sn}.pdf"
    import config
    HTML(string=html_str, base_url=config.STATIC_DIR.as_uri() + '/').write_pdf(str(pdf_path))
    return str(pdf_path)
