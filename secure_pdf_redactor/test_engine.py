from pathlib import Path
import tempfile

import pymupdf

from redaction_engine import redact_pdf, scan_pdf


def make_sample(path: Path) -> None:
    doc = pymupdf.open()
    p = doc.new_page(width=595, height=842)
    p.insert_text((72, 100), "Email: jane.doe@example.com")
    p.insert_text((72, 130), "Phone: +61 4 1234 5678")
    p.insert_text((72, 160), "DOB: 09/08/1999")
    p.insert_text((72, 190), "MNI: 12345678")
    p.insert_text((72, 220), "Other ID: 87654321")
    doc.save(path)
    doc.close()


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / "sample.pdf"
        out = td / "sample_redacted.pdf"
        make_sample(src)
        scan = scan_pdf(src)
        assert len(scan.findings) == 5, [(f.category, f.text) for f in scan.findings]
        assert not scan.suspicious_pages
        result = redact_pdf(scan, [f.key for f in scan.findings], out, dpi=150)
        assert result.output_path.exists()

        redacted = pymupdf.open(out)
        assert redacted.page_count == 1
        assert redacted[0].get_text("text").strip() == ""
        redacted.close()
        print("PASS", result.sha256)


if __name__ == "__main__":
    main()
