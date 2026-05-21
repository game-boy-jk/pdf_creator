from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import fitz

from app.pdf.fonts import resolve_font_path
from app.pdf.layout import (
    MIN_FONT_SIZE,
    TextStyle,
    line_target_rect,
    line_text,
    placeholder_target_rect,
    style_at_rect,
)

PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z0-9_.-]+)\s*}}")

FontLoader = Callable[[], bytes | None]


class PdfFillError(Exception):
    """Исключение для ошибок заполнения PDF."""
    pass


@dataclass(frozen=True)
class _Replacement:
    key: str
    value: str
    # rect — область, которую стираем через redact
    erase_rect: fitz.Rect
    # rect — область куда вставляем новый текст (может быть шире erase_rect)
    insert_rect: fitz.Rect
    style: TextStyle
    font_path: str | None


def fill_pdf(
    src: bytes,
    data: dict[str, str],
    *,
    replace: dict[str, str] | None = None,
    fallback_font: FontLoader | None = None,
) -> bytes:
    """
    Заполняет PDF-шаблон данными и возвращает готовый PDF.

    Data — значения для placeholder'ов вида {{key}}
    replace — прямая замена текста: {'старый текст': 'новый текст'}
    fallback_font — callable, возвращает байты TTF-шрифта из S3
    """
    replace = replace or {}

    if not data and not replace:
        raise PdfFillError("data or replace must not be empty")

    try:
        doc = fitz.open(stream=src, filetype="pdf")
    except (fitz.EmptyFileError, fitz.FileDataError) as exc:
        raise PdfFillError(f"Failed to open PDF template: {exc}") from exc

    try:
        replacements = _collect_replacements(doc, data, replace, fallback_font)
        _apply_replacements(doc, replacements)
        return doc.tobytes(garbage=4, deflate=True)
    finally:
        doc.close()


def _collect_replacements(
    doc: fitz.Document,
    data: dict[str, str],
    replace: dict[str, str],
    fallback_font: FontLoader | None,
) -> dict[int, list[_Replacement]]:
    result: dict[int, list[_Replacement]] = {}

    # Состояние для валидации placeholder'ов
    found_keys: set[str] = set()
    missing_keys: set[str] = set()
    has_placeholders = False
    not_found = set(replace)

    for page_num, page in enumerate(doc):
        # get_text("dict") один раз на страницу — используем для всего:
        # поиска placeholder'ов, replace и определения стиля
        page_layout = page.get_text("dict")
        page_text = _extract_plain_text(page_layout)

        if data:
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
                        font_path=resolve_font_path(style.font, doc, page, fallback_font),
                    ))

        if replace:
            for old_text, new_text in replace.items():
                for erase_rect, value in _find_line_replacements(page_layout, old_text, new_text):
                    not_found.discard(old_text)
                    style = style_at_rect(page_layout, erase_rect)
                    result.setdefault(page_num, []).append(_Replacement(
                        key=old_text,
                        value=value,
                        erase_rect=erase_rect,
                        insert_rect=line_target_rect(page, erase_rect, style.font_size),
                        style=style,
                        font_path=resolve_font_path(style.font, doc, page, fallback_font),
                    ))

    _validate(data, replace, found_keys, missing_keys, has_placeholders, not_found, result)
    return result


def _validate(
    data: dict[str, str],
    replace: dict[str, str],
    found_keys: set[str],
    missing_keys: set[str],
    has_placeholders: bool,
    not_found: set[str],
    result: dict,
) -> None:
    if data and not has_placeholders:
        raise PdfFillError("PDF template has no placeholders")

    if missing_keys:
        raise PdfFillError(f"Missing values for PDF placeholders: {', '.join(sorted(missing_keys))}")

    unused = set(data) - found_keys
    if unused and not found_keys:
        raise PdfFillError(f"Unknown PDF placeholders: {', '.join(sorted(unused))}")

    if not_found:
        raise PdfFillError(f"Text to replace not found in PDF: {', '.join(sorted(not_found))}")

    if not result:
        raise PdfFillError("PDF template has no matching text")


def _extract_plain_text(page_layout: dict[str, Any]) -> str:
    """Собирает plain text из dict-структуры страницы без повторного вызова get_text."""
    return "\n".join(
        line_text(line)
        for block in page_layout.get("blocks", [])
        for line in block.get("lines", [])
    )


def _find_line_replacements(
    page_layout: dict[str, Any],
    old_text: str,
    new_text: str,
) -> list[tuple[fitz.Rect, str]]:
    """Ищет строки содержащие old_text, возвращает их rect + текст с заменой."""
    return [
        (fitz.Rect(line["bbox"]), line_text(line).replace(old_text, new_text))
        for block in page_layout.get("blocks", [])
        for line in block.get("lines", [])
        if old_text in line_text(line)
    ]


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
    """
    Вставляет текст в insert_rect, уменьшая шрифт если не влезает.
    Если даже при MIN_FONT_SIZE не помещается — бросаем ошибку.
    """
    font_name = _resolve_font_name(item)
    font_size = item.style.font_size

    while font_size >= MIN_FONT_SIZE:
        remaining = page.insert_textbox(
            item.insert_rect,
            item.value,
            fontsize=font_size,
            fontname=font_name,
            fontfile=item.font_path,
            color=item.style.color,
            align=fitz.TEXT_ALIGN_LEFT,
            overlay=True,
        )
        if remaining >= 0:
            return
        font_size -= 0.5

    # Последняя попытка с минимальным размером
    remaining = page.insert_textbox(
        item.insert_rect,
        item.value,
        fontsize=MIN_FONT_SIZE,
        fontname=font_name,
        fontfile=item.font_path,
        color=item.style.color,
        align=fitz.TEXT_ALIGN_LEFT,
        overlay=True,
    )
    if remaining < 0:
        raise PdfFillError(f"Value does not fit placeholder: {item.key}")


def _resolve_font_name(item: _Replacement) -> str:
    """
    PyMuPDF требует уникальное имя при регистрации шрифта через fontfile.
    Для встроенных шрифтов используем стандартные псевдонимы.
    """
    if item.font_path:
        return f"f{abs(hash(item.font_path)) % 10**8}"

    aliases = {"Helvetica": "helv", "Times-Roman": "tiro", "Courier": "cour"}
    return aliases.get(item.style.font, "helv")