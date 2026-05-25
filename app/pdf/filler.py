import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import fitz

from app.pdf.fonts import resolve_font_path
from app.pdf.layout import (
    MIN_FONT_SIZE,
    TextStyle,
    line_text,
    placeholder_target_rect,
    style_at_rect,
)

PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z0-9_.-]+)\s*}}")

FontLoader = Callable[[], bytes]


class PdfFillError(Exception):
    pass


@dataclass(frozen=True)
class _Replacement:
    key: str
    value: str
    erase_rect: fitz.Rect
    insert_rect: fitz.Rect
    style: TextStyle
    font_path: str


def fill_pdf(
    src: bytes,
    data: dict[str, str],
    *,
    fallback_font: FontLoader,
) -> bytes:
    """
    Заполняет PDF-шаблон данными и возвращает готовый PDF.
    data — значения для placeholder'ов вида {{key}}.
    fallback_font — callable, возвращает байты TTF-шрифта из MinIO.
    """
    if not data:
        raise PdfFillError("data must not be empty")

    try:
        doc = fitz.open(stream=src, filetype="pdf")
    except (fitz.EmptyFileError, fitz.FileDataError) as exc:
        raise PdfFillError(f"Failed to open PDF template: {exc}") from exc

    try:
        replacements = _collect_replacements(doc, data, fallback_font)
        _apply_replacements(doc, replacements)
        return doc.tobytes(garbage=4, deflate=True)
    finally:
        doc.close()


def _collect_replacements(
    doc: fitz.Document,
    data: dict[str, str],
    fallback_font: FontLoader,
) -> dict[int, list[_Replacement]]:
    result: dict[int, list[_Replacement]] = {}
    found_keys: set[str] = set()
    missing_keys: set[str] = set()
    has_placeholders = False

    for page_num, page in enumerate(doc):
        # get_text("dict") один раз на страницу — используем для поиска
        # placeholder'ов и определения стиля текста
        page_layout = page.get_text("dict")
        page_text = _extract_plain_text(page_layout)

        markers = {
            m.group(0): m.group(1)
            for m in PLACEHOLDER_RE.finditer(page_text)
        }
        if markers:
            has_placeholders = True

        for marker, key in markers.items():
            if key not in data:
                missing_keys.add(key)
                continue

            for erase_rect in page.search_for(marker):
                found_keys.add(key)
                style = style_at_rect(page_layout, erase_rect)
                result.setdefault(page_num, []).append(_Replacement(
                    key=key,
                    value=str(data[key]),
                    erase_rect=erase_rect,
                    insert_rect=placeholder_target_rect(page, page_layout, erase_rect, style.font_size),
                    style=style,
                    font_path=resolve_font_path(fallback_font),
                ))

    _validate(data, found_keys, missing_keys, has_placeholders, result)
    return result


def _validate(
    data: dict[str, str],
    found_keys: set[str],
    missing_keys: set[str],
    has_placeholders: bool,
    result: dict,
) -> None:
    if not has_placeholders:
        raise PdfFillError("PDF template has no placeholders")

    if missing_keys:
        raise PdfFillError(f"Missing values for PDF placeholders: {', '.join(sorted(missing_keys))}")

    unused = set(data) - found_keys
    if unused and not found_keys:
        raise PdfFillError(f"Unknown PDF placeholders: {', '.join(sorted(unused))}")

    if not result:
        raise PdfFillError("PDF template has no matching text")


def _extract_plain_text(page_layout: dict[str, Any]) -> str:
    """Собирает plain text из dict-структуры страницы без повторного вызова get_text."""
    return "\n".join(
        line_text(line)
        for block in page_layout.get("blocks", [])
        for line in block.get("lines", [])
    )


def _apply_replacements(
    doc: fitz.Document,
    replacements: dict[int, list[_Replacement]],
) -> None:
    for page_num, items in replacements.items():
        page = doc[page_num]

        # Сначала помечаем все области для стирания...
        for item in items:
            page.add_redact_annot(item.erase_rect, fill=(1, 1, 1))

        # ...потом стираем одним вызовом (эффективнее чем по одному)
        page.apply_redactions()

        for item in items:
            _insert_text(page, item)


def _insert_text(page: fitz.Page, item: _Replacement) -> None:
    font_name = f"f{abs(hash(item.font_path)) % 10**8}"
    font_size = item.style.font_size

    while font_size >= MIN_FONT_SIZE:
        if _try_insert(page, item, font_name, font_size) >= 0:
            return
        font_size -= 0.5

    if _try_insert(page, item, font_name, MIN_FONT_SIZE) < 0:
        raise PdfFillError(f"Value does not fit placeholder: {item.key}")


def _try_insert(page: fitz.Page, item: _Replacement, font_name: str, font_size: float) -> float:
    return page.insert_textbox(
        item.insert_rect,
        item.value,
        fontsize=font_size,
        fontname=font_name,
        fontfile=item.font_path,
        color=item.style.color,
        align=fitz.TEXT_ALIGN_LEFT,
        overlay=True,
    )
