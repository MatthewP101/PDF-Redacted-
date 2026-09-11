from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pymupdf


CATEGORY_ORDER = {
    "MNI": 0,
    "Email": 1,
    "Phone": 2,
    "Date": 3,
    "Identifier": 4,
}

PATTERNS = {
    "Email": re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
    "Phone": re.compile(r"(?:\+61\s?\d(?:[\s-]?\d){8})|(?:0\d(?:[\s-]?\d){8})", re.IGNORECASE),
    "Date": re.compile(r"\b(?:[0-2]?\d|3[0-1])[\/\-.](?:0?\d|1[0-2])[\/\-.](?:\d{2}|\d{4})\b", re.IGNORECASE),
    "MNI": re.compile(r"MNI\s*:?\s*\d{6,12}", re.IGNORECASE),
    "Identifier": re.compile(r"\b\d{6,12}\b", re.IGNORECASE),
}


@dataclass(frozen=True)
class Occurrence:
    category: str
    text: str
    page_index: int
    rect: tuple[float, float, float, float]


@dataclass
class Finding:
    key: str
    category: str
    text: str
    occurrences: list[Occurrence]

    @property
    def count(self) -> int:
        return len(self.occurrences)

    @property
    def pages(self) -> list[int]:
        return sorted({o.page_index + 1 for o in self.occurrences})


@dataclass
class ScanResult:
    input_path: Path
    findings: list[Finding]
    suspicious_pages: list[int]
    blocked_reasons: list[str]
    page_count: int
    encrypted: bool


@dataclass
class RedactionResult:
    output_path: Path
    redacted_occurrences: int
    redacted_values: int
    sha256: str
    page_count: int


class RedactionError(RuntimeError):
    pass


def _union_char_rects(chars: list[dict], start: int, end: int) -> tuple[float, float, float, float]:
    selected = chars[start:end]
    if not selected:
        raise RedactionError("Internal error: empty character range for finding")

    x0 = min(float(c["bbox"][0]) for c in selected)
    y0 = min(float(c["bbox"][1]) for c in selected)
    x1 = max(float(c["bbox"][2]) for c in selected)
    y1 = max(float(c["bbox"][3]) for c in selected)

    # Tiny safety margin to avoid leaving anti-aliased edge pixels.
    margin = 0.8
    return (x0 - margin, y0 - margin, x1 + margin, y1 + margin)


def _iter_line_chars(page: pymupdf.Page) -> Iterable[tuple[str, list[dict]]]:
    raw = page.get_text("rawdict", sort=True)
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            chars: list[dict] = []
            for span in line.get("spans", []):
                chars.extend(span.get("chars", []))
            if chars:
                yield "".join(c.get("c", "") for c in chars), chars


def _normalised_key(category: str, text: str) -> str:
    if category in {"Email", "MNI"}:
        value = text.casefold()
    else:
        value = text
    return f"{category}\x1f{value}"


def _page_is_suspicious(page: pymupdf.Page, text: str) -> bool:
    # Fail-safe signal for image-only/scanned or badly encoded pages.
    meaningful = sum(ch.isalnum() for ch in text)
    replacement_count = text.count("\ufffd")
    replacement_ratio = replacement_count / max(1, len(text))
    has_images = bool(page.get_images(full=True))

    if has_images and meaningful < 5:
        return True
    if replacement_ratio > 0.10 and len(text) > 20:
        return True
    return False


def scan_pdf(path: str | Path, password: str | None = None) -> ScanResult:
    input_path = Path(path).expanduser().resolve()
    if not input_path.is_file():
        raise RedactionError("The selected PDF does not exist.")
    if input_path.suffix.lower() != ".pdf":
        raise RedactionError("Only PDF files are supported.")

    try:
        doc = pymupdf.open(input_path)
    except Exception as exc:
        raise RedactionError(f"Could not open PDF: {exc}") from exc

    try:
        encrypted = bool(doc.needs_pass)
        if encrypted:
            if not password:
                raise RedactionError("PASSWORD_REQUIRED")
            if not doc.authenticate(password):
                raise RedactionError("The PDF password was not accepted.")

        occurrences: list[Occurrence] = []
        suspicious_pages: list[int] = []
        blocked_reasons: list[str] = []

        for page_index, page in enumerate(doc):
            page_text = page.get_text("text", sort=True)
            if _page_is_suspicious(page, page_text):
                suspicious_pages.append(page_index + 1)

            widgets = list(page.widgets() or [])
            if widgets:
                blocked_reasons.append(
                    f"Page {page_index + 1} contains interactive form fields; this build refuses "
                    "to export them because field values are not covered by the regex text scan."
                )

            for line_text, chars in _iter_line_chars(page):
                # Detect MNI first and remember its character ranges so the
                # generic 6-12 digit rule does not create a duplicate nested hit.
                mni_ranges: list[tuple[int, int]] = []
                for m in PATTERNS["MNI"].finditer(line_text):
                    mni_ranges.append((m.start(), m.end()))
                    occurrences.append(
                        Occurrence(
                            category="MNI",
                            text=m.group(0).strip(),
                            page_index=page_index,
                            rect=_union_char_rects(chars, m.start(), m.end()),
                        )
                    )

                for category in ("Email", "Phone", "Date", "Identifier"):
                    for m in PATTERNS[category].finditer(line_text):
                        if category == "Identifier":
                            if any(m.start() >= a and m.end() <= b for a, b in mni_ranges):
                                continue

                        occurrences.append(
                            Occurrence(
                                category=category,
                                text=m.group(0).strip(),
                                page_index=page_index,
                                rect=_union_char_rects(chars, m.start(), m.end()),
                            )
                        )

        grouped: dict[str, Finding] = {}
        for occ in occurrences:
            key = _normalised_key(occ.category, occ.text)
            if key not in grouped:
                grouped[key] = Finding(
                    key=key,
                    category=occ.category,
                    text=occ.text,
                    occurrences=[],
                )
            grouped[key].occurrences.append(occ)

        findings = sorted(
            grouped.values(),
            key=lambda f: (CATEGORY_ORDER.get(f.category, 99), f.text.casefold()),
        )

        return ScanResult(
            input_path=input_path,
            findings=findings,
            suspicious_pages=suspicious_pages,
            blocked_reasons=blocked_reasons,
            page_count=doc.page_count,
            encrypted=encrypted,
        )
    finally:
        doc.close()


def _verify_source_redactions(doc: pymupdf.Document, selected: list[Finding]) -> None:
    remaining_text = "\n".join(page.get_text("text", sort=True) for page in doc)
    folded = remaining_text.casefold()

    failures: list[str] = []
    for finding in selected:
        needle = finding.text.casefold()
        if needle and needle in folded:
            failures.append(f"{finding.category}: {finding.text}")

    if failures:
        short = "; ".join(failures[:5])
        more = "" if len(failures) <= 5 else f" (+{len(failures) - 5} more)"
        raise RedactionError(
            "Verification failed before export. One or more selected values are still "
            f"extractable: {short}{more}"
        )


def _flatten_to_new_pdf(source: pymupdf.Document, output_path: Path, dpi: int) -> None:
    out = pymupdf.open()
    try:
        for page in source:
            # Do not carry source annotations/comments into the flattened output.
            pix = page.get_pixmap(dpi=dpi, alpha=False, annots=False)
            new_page = out.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, pixmap=pix)

        # A brand-new document containing only rendered page images avoids
        # carrying over metadata, annotations, forms, JS, attachments, layers,
        # object streams, hidden text, or revision history from the source PDF.
        out.set_metadata({})
        if hasattr(out, "del_xml_metadata"):
            out.del_xml_metadata()

        out.save(
            output_path,
            garbage=4,
            clean=True,
            deflate=True,
            deflate_images=True,
            incremental=False,
        )
    finally:
        out.close()


def _verify_flattened_output(output_path: Path, expected_pages: int) -> None:
    try:
        out = pymupdf.open(output_path)
    except Exception as exc:
        raise RedactionError(f"Could not reopen exported PDF for verification: {exc}") from exc

    try:
        if out.page_count != expected_pages:
            raise RedactionError(
                f"Verification failed: expected {expected_pages} pages, got {out.page_count}."
            )

        # Secure-flatten mode intentionally creates an image-only PDF. Any
        # extractable text means source structure unexpectedly survived.
        unexpected_text = []
        for i, page in enumerate(out):
            if page.get_text("text").strip():
                unexpected_text.append(i + 1)

        if unexpected_text:
            raise RedactionError(
                "Verification failed: exported PDF unexpectedly contains extractable text "
                f"on page(s) {', '.join(map(str, unexpected_text))}."
            )
    finally:
        out.close()


def redact_pdf(
    scan: ScanResult,
    selected_keys: Iterable[str],
    output_path: str | Path,
    password: str | None = None,
    dpi: int = 200,
) -> RedactionResult:
    selected_set = set(selected_keys)
    selected = [f for f in scan.findings if f.key in selected_set]

    if not selected:
        raise RedactionError("Select at least one detected value to redact.")
    if scan.suspicious_pages:
        pages = ", ".join(map(str, scan.suspicious_pages))
        raise RedactionError(
            "Secure export is blocked because some pages may be scanned/image-only or "
            f"have unusable text encoding: {pages}. OCR/manual review is required first."
        )
    if scan.blocked_reasons:
        raise RedactionError("Secure export is blocked. " + " ".join(scan.blocked_reasons))
    if dpi not in {150, 200, 300}:
        raise RedactionError("DPI must be 150, 200, or 300.")

    output = Path(output_path).expanduser().resolve()
    if output.suffix.lower() != ".pdf":
        output = output.with_suffix(".pdf")
    if output == scan.input_path:
        raise RedactionError("The app will not overwrite the original PDF. Choose a new filename.")

    try:
        doc = pymupdf.open(scan.input_path)
    except Exception as exc:
        raise RedactionError(f"Could not reopen source PDF: {exc}") from exc

    try:
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                raise RedactionError("The PDF password is required again for export.")

        page_rects: dict[int, list[tuple[float, float, float, float]]] = {}
        redacted_occurrences = 0
        for finding in selected:
            for occ in finding.occurrences:
                page_rects.setdefault(occ.page_index, []).append(occ.rect)
                redacted_occurrences += 1

        for page_index, rects in page_rects.items():
            page = doc[page_index]
            for rect_tuple in rects:
                rect = pymupdf.Rect(rect_tuple) & page.rect
                if rect.is_empty:
                    continue
                page.add_redact_annot(rect, fill=(0, 0, 0), cross_out=False)
            # Defaults remove text and blank overlapping image pixels.
            page.apply_redactions()

        _verify_source_redactions(doc, selected)
        _flatten_to_new_pdf(doc, output, dpi)
    finally:
        doc.close()

    _verify_flattened_output(output, scan.page_count)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()

    return RedactionResult(
        output_path=output,
        redacted_occurrences=redacted_occurrences,
        redacted_values=len(selected),
        sha256=digest,
        page_count=scan.page_count,
    )
