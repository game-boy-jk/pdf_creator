from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import fitz


class PdfFillError(Exception):
    pass


FontResolver = Callable[[], bytes | None]
FontCache = dict[str, str | None]

PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z0-9_.-]+)\s*}}")
DEFAULT_MARGIN = 36
LINE_HEIGHT_FACTOR = 1.15
MIN_FONT_SIZE = 10.0


@dataclass(frozen=True)
class TextStyle:
    font: str
    font_size: float
    color: tuple[float, float, float]


@dataclass(frozen=True)
class Replacement:
    key: str
    value: str
    rect: fitz.Rect
    target_rect: fitz.Rect
    style: TextStyle
    font_file: str | None


def fill_pdf(
    src: bytes,
    data: dict[str, str],
    *,
    replace: dict[str, str] | None = None,
    fallback_font: FontResolver | None = None,
) -> bytes:
    replace = replace or {}
    if not data and not replace:
        raise PdfFillError("data or replace must not be empty")

    try:
        document = fitz.open(stream=src, filetype="pdf")
    except (fitz.EmptyFileError, fitz.FileDataError) as exc:
        raise PdfFillError(f"Failed to open PDF template: {exc}") from exc

    temp_fonts: list[str] = []

    try:
        replacements: dict[int, list[Replacement]] = {}
        font_cache: FontCache = {}

        if data:
            _merge_replacements(
                replacements,
                _collect_placeholder_replacements(
                    document,
                    data,
                    fallback_font,
                    temp_fonts,
                    font_cache,
                ),
            )

        if replace:
            _merge_replacements(
                replacements,
                _collect_text_replacements(
                    document,
                    replace,
                    fallback_font,
                    temp_fonts,
                    font_cache,
                ),
            )

        if not replacements:
            raise PdfFillError("PDF template has no matching text")

        for page_number, page_replacements in replacements.items():
            page = document[page_number]
            for item in page_replacements:
                page.add_redact_annot(item.rect, fill=(1, 1, 1))

            page.apply_redactions()

            for item in page_replacements:
                _insert_value(page, item)

        return document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()
        for path in temp_fonts:
            try:
                os.unlink(path)
            except OSError:
                pass


def _collect_placeholder_replacements(
    document: fitz.Document,
    data: dict[str, str],
    fallback_font: FontResolver | None,
    temp_fonts: list[str],
    font_cache: FontCache,
) -> dict[int, list[Replacement]]:
    result: dict[int, list[Replacement]] = {}
    found_keys: set[str] = set()
    missing_keys: set[str] = set()
    has_placeholders = False

    for page_number, page in enumerate(document):
        text = page.get_text("text")
        markers = {
            match.group(0): match.group(1)
            for match in PLACEHOLDER_RE.finditer(text)
        }
        has_placeholders = has_placeholders or bool(markers)
        page_text = page.get_text("dict")

        for marker, key in markers.items():
            if key not in data:
                missing_keys.add(key)
                continue

            rects = page.search_for(marker)
            if not rects:
                continue

            found_keys.add(key)
            for rect in rects:
                style = _style_for_rect(page_text, rect)
                font_file = _font_file_for_style(
                    document,
                    page,
                    style,
                    fallback_font,
                    temp_fonts,
                    font_cache,
                )
                result.setdefault(page_number, []).append(
                    Replacement(
                        key=key,
                        value=str(data[key]),
                        rect=rect,
                        target_rect=_target_rect(page, page_text, rect, style.font_size),
                        style=style,
                        font_file=font_file,
                    )
                )

    if missing_keys:
        names = ", ".join(sorted(missing_keys))
        raise PdfFillError(f"Missing values for PDF placeholders: {names}")

    if not has_placeholders:
        raise PdfFillError("PDF template has no placeholders")

    unused = set(data) - found_keys
    if unused and not found_keys:
        names = ", ".join(sorted(unused))
        raise PdfFillError(f"Unknown PDF placeholders: {names}")

    return result


def _collect_text_replacements(
    document: fitz.Document,
    replace: dict[str, str],
    fallback_font: FontResolver | None,
    temp_fonts: list[str],
    font_cache: FontCache,
) -> dict[int, list[Replacement]]:
    result: dict[int, list[Replacement]] = {}
    missing: set[str] = set(replace)

    for page_number, page in enumerate(document):
        page_text = page.get_text("dict")

        for old_text, new_text in replace.items():
            line_replacements = _line_replacements(page_text, old_text, str(new_text))
            if not line_replacements:
                continue

            missing.discard(old_text)
            for rect, value in line_replacements:
                style = _style_for_rect(page_text, rect)
                font_file = _font_file_for_style(
                    document,
                    page,
                    style,
                    fallback_font,
                    temp_fonts,
                    font_cache,
                )
                result.setdefault(page_number, []).append(
                    Replacement(
                        key=old_text,
                        value=value,
                        rect=rect,
                        target_rect=_line_target_rect(page, rect, style.font_size),
                        style=style,
                        font_file=font_file,
                    )
                )

    if missing:
        names = ", ".join(sorted(missing))
        raise PdfFillError(f"Text to replace not found in PDF: {names}")

    return result


def _line_replacements(
    page_text: dict[str, Any],
    old_text: str,
    new_text: str,
) -> list[tuple[fitz.Rect, str]]:
    result: list[tuple[fitz.Rect, str]] = []

    for block in page_text.get("blocks", []):
        for line in block.get("lines", []):
            text = _line_text(line)
            if old_text not in text:
                continue
            result.append((fitz.Rect(line["bbox"]), text.replace(old_text, new_text)))

    return result


def _merge_replacements(
    target: dict[int, list[Replacement]],
    source: dict[int, list[Replacement]],
) -> None:
    for page_number, items in source.items():
        target.setdefault(page_number, []).extend(items)


def _style_for_rect(page_text: dict[str, Any], rect: fitz.Rect) -> TextStyle:
    best_span: dict[str, Any] | None = None
    best_area = 0.0

    for block in page_text.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                span_rect = fitz.Rect(span["bbox"])
                area = span_rect.intersect(rect).get_area()
                if area > best_area:
                    best_area = area
                    best_span = span

    if not best_span:
        return TextStyle(font="helv", font_size=11.0, color=(0, 0, 0))

    return TextStyle(
        font=str(best_span.get("font") or "helv"),
        font_size=float(best_span.get("size") or 11.0),
        color=_pdf_color(int(best_span.get("color") or 0)),
    )


def _font_file_for_style(
    document: fitz.Document,
    page: fitz.Page,
    style: TextStyle,
    fallback_font: FontResolver | None,
    temp_fonts: list[str],
    font_cache: FontCache,
) -> str | None:
    if style.font in {"helv", "Helvetica", "Times-Roman", "Courier"}:
        return None

    if style.font in font_cache:
        return font_cache[style.font]

    font_bytes = fallback_font() if fallback_font is not None else None
    if font_bytes is None:
        font_bytes = _embedded_font(document, page, style.font)

    if not font_bytes:
        font_cache[style.font] = None
        return None

    temp = tempfile.NamedTemporaryFile(prefix="pdf-font-", suffix=".ttf", delete=False)
    try:
        temp.write(font_bytes)
        font_cache[style.font] = temp.name
        return temp.name
    finally:
        temp.close()
        temp_fonts.append(temp.name)


def _embedded_font(document: fitz.Document, page: fitz.Page, span_font: str) -> bytes | None:
    embedded_fonts: list[bytes] = []

    for font in page.get_fonts(full=True):
        xref = int(font[0])
        base_font = str(font[3])
        extracted = document.extract_font(xref)
        font_bytes = extracted[3] or None
        if font_bytes:
            embedded_fonts.append(font_bytes)

        if base_font == span_font or base_font.endswith(f"+{span_font}") or base_font.endswith(span_font):
            return font_bytes

    if len(embedded_fonts) == 1:
        return embedded_fonts[0]

    return None


def _insert_value(page: fitz.Page, item: Replacement) -> None:
    rect = item.target_rect
    font_name = _font_name(item)
    font_size = item.style.font_size

    while font_size >= MIN_FONT_SIZE:
        remaining = page.insert_textbox(
            rect,
            item.value,
            fontsize=font_size,
            fontname=font_name,
            fontfile=item.font_file,
            color=item.style.color,
            align=fitz.TEXT_ALIGN_LEFT,
            overlay=True,
        )
        if remaining >= 0:
            return

        font_size -= 0.5

    remaining = page.insert_textbox(
        rect,
        item.value,
        fontsize=MIN_FONT_SIZE,
        fontname=font_name,
        fontfile=item.font_file,
        color=item.style.color,
        align=fitz.TEXT_ALIGN_LEFT,
        overlay=True,
    )
    if remaining < 0:
        raise PdfFillError(f"Value does not fit placeholder: {item.key}")


def _target_rect(
    page: fitz.Page,
    page_text: dict[str, Any],
    marker_rect: fitz.Rect,
    font_size: float,
) -> fitz.Rect:
    line_height = max(font_size * LINE_HEIGHT_FACTOR, marker_rect.height)
    same_line = _same_line(page_text, marker_rect)

    if same_line and same_line.x1 > marker_rect.x1 + font_size:
        return fitz.Rect(
            marker_rect.x0,
            marker_rect.y0,
            marker_rect.x1,
            marker_rect.y0 + line_height,
        )

    next_line_y = _next_line_y(page_text, marker_rect)
    max_y = marker_rect.y0 + line_height * 4
    if next_line_y is not None:
        max_y = min(max_y, next_line_y - 1)

    return fitz.Rect(
        marker_rect.x0,
        marker_rect.y0,
        max(marker_rect.x1, page.rect.x1 - DEFAULT_MARGIN),
        min(page.rect.y1 - DEFAULT_MARGIN, max_y),
    )


def _line_target_rect(page: fitz.Page, line_rect: fitz.Rect, font_size: float) -> fitz.Rect:
    line_height = max(font_size * 1.8, line_rect.height)
    return fitz.Rect(
        line_rect.x0,
        line_rect.y0,
        page.rect.x1 - DEFAULT_MARGIN,
        line_rect.y0 + line_height,
    )


def _same_line(page_text: dict[str, Any], rect: fitz.Rect) -> fitz.Rect | None:
    for block in page_text.get("blocks", []):
        for line in block.get("lines", []):
            if not _line_text(line).strip():
                continue
            line_rect = fitz.Rect(line["bbox"])
            if line_rect.y0 <= rect.y1 and line_rect.y1 >= rect.y0:
                return line_rect
    return None


def _next_line_y(page_text: dict[str, Any], rect: fitz.Rect) -> float | None:
    candidates: list[float] = []
    for block in page_text.get("blocks", []):
        for line in block.get("lines", []):
            if not _line_text(line).strip():
                continue
            line_rect = fitz.Rect(line["bbox"])
            if line_rect.y0 > rect.y1:
                candidates.append(line_rect.y0)
    return min(candidates) if candidates else None


def _line_text(line: dict[str, Any]) -> str:
    return "".join(str(span.get("text", "")) for span in line.get("spans", []))


def _font_name(item: Replacement) -> str:
    if item.font_file:
        return f"f{abs(hash(item.font_file))}"
    if item.style.font == "Helvetica":
        return "helv"
    if item.style.font == "Times-Roman":
        return "tiro"
    if item.style.font == "Courier":
        return "cour"
    return "helv"


def _pdf_color(value: int) -> tuple[float, float, float]:
    red = ((value >> 16) & 255) / 255
    green = ((value >> 8) & 255) / 255
    blue = (value & 255) / 255
    return red, green, blue
