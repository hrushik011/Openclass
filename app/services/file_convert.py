"""Secure .docx <-> .pdf conversion for Knowledge Hub utility."""

from __future__ import annotations

import logging
import shutil
import subprocess
import uuid
from pathlib import Path

from docx import Document
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

logger = logging.getLogger("openclass.convert")

ALLOWED_SOURCE = {".docx", ".pdf"}
ALLOWED_TARGET = {"docx", "pdf"}


def _docx_to_pdf_simple(src: Path, dest: Path) -> None:
    """Fallback PDF export: paragraph text via python-docx + reportlab."""
    doc = Document(str(src))
    c = canvas.Canvas(str(dest), pagesize=letter)
    width, height = letter
    y = height - 72
    c.setFont("Helvetica", 11)
    for para in doc.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        for line in _wrap_text(text, 92):
            if y < 72:
                c.showPage()
                c.setFont("Helvetica", 11)
                y = height - 72
            c.drawString(72, y, line[:500])
            y -= 14
    c.save()


def _wrap_text(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join(current + [word])
        if len(trial) > width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines or [text[:width]]


def _pdf_to_docx(src: Path, dest: Path) -> None:
    from pdf2docx import Converter

    cv = Converter(str(src))
    try:
        cv.convert(str(dest))
    finally:
        cv.close()


def _try_libreoffice_docx_to_pdf(src: Path, dest: Path) -> bool:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return False
    outdir = dest.parent
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(src)],
            check=True,
            capture_output=True,
            timeout=120,
        )
        produced = outdir / f"{src.stem}.pdf"
        if produced.exists() and produced != dest:
            produced.replace(dest)
        return dest.exists()
    except Exception as exc:
        logger.warning("LibreOffice conversion failed: %s", exc)
        return False


def convert_document(src: Path, target_format: str, work_dir: Path) -> tuple[Path, str]:
    """
    Convert uploaded file to target_format ('pdf' | 'docx').
    Returns (output_path, download_filename).
    """
    target_format = (target_format or "").lower().strip()
    if target_format not in ALLOWED_TARGET:
        raise ValueError(f"Unsupported target format '{target_format}'. Use pdf or docx.")

    suffix = src.suffix.lower()
    if suffix not in ALLOWED_SOURCE:
        raise ValueError("Only .docx and .pdf uploads are supported.")

    if suffix == f".{target_format}":
        raise ValueError(f"File is already .{target_format}.")

    token = uuid.uuid4().hex[:10]
    dest_name = f"{src.stem}-converted-{token}.{target_format}"
    dest = work_dir / dest_name

    if suffix == ".pdf" and target_format == "docx":
        _pdf_to_docx(src, dest)
    elif suffix == ".docx" and target_format == "pdf":
        if not _try_libreoffice_docx_to_pdf(src, dest):
            _docx_to_pdf_simple(src, dest)
    else:
        raise ValueError("Invalid conversion path.")

    if not dest.exists():
        raise RuntimeError("Conversion produced no output file.")

    return dest, dest_name
