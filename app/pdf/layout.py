from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import fitz

DEFAULT_MARGIN = 36  # отступ от края страницы в pt
LINE_HEIGHT_FACTOR = 1.15  # запас по высоте строки относительно font_size
MIN_FONT_SIZE = 10.0


@dataclass(frozen=True)
class TextStyle:
    font: str
    font_size: float
    color: tuple[float, float, float]


def style_at_rect(page_text: dict[str, Any], rect: fitz.Rect) -> TextStyle:
    """Находит span с максимальным перекрытием с rect и берёт из него стиль."""
    best_span: dict[str, Any] | None = None
    best_area = 0.0

    for block in page_text.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                area = fitz.Rect(span["bbox"]).intersect(rect).get_area()
                if area > best_area:
                    best_area = area
                    best_span = span

    if not best_span:
        return TextStyle(font="helv", font_size=11.0, color=(0.0, 0.0, 0.0))

    return TextStyle(
        font=str(best_span.get("font") or "helv"),
        font_size=float(best_span.get("size") or 11.0),
        color=_color_from_int(int(best_span.get("color") or 0)),
    )


def placeholder_target_rect(
    page: fitz.Page,
    page_text: dict[str, Any],
    marker_rect: fitz.Rect,
    font_size: float,
) -> fitz.Rect:
    """
    Вычисляет rect для вставки значения вместо placeholder'а.

    Если после placeholder'а на той же строке есть другой текст —
    ограничиваем rect по x1 самого marker'а (текст рядом не перекрываем).
    Иначе растягиваем до правого края страницы и вниз до следующей строки.
    """
    line_height = max(font_size * LINE_HEIGHT_FACTOR, marker_rect.height)
    same_line_rect = _find_same_line(page_text, marker_rect)

    if same_line_rect and same_line_rect.x1 > marker_rect.x1 + font_size:
        # Есть текст справа — не выходим за правую границу marker'а
        return fitz.Rect(
            marker_rect.x0,
            marker_rect.y0,
            marker_rect.x1,
            marker_rect.y0 + line_height,
        )

    next_y = _next_line_top(page_text, marker_rect)
    bottom = min(
        marker_rect.y0 + line_height * 4,
        next_y - 1 if next_y is not None else float("inf"),
        page.rect.y1 - DEFAULT_MARGIN,
    )

    return fitz.Rect(
        marker_rect.x0,
        marker_rect.y0,
        page.rect.x1 - DEFAULT_MARGIN,
        bottom,
    )


def line_target_rect(page: fitz.Page, line_rect: fitz.Rect, font_size: float) -> fitz.Rect:
    """
    Rect для замены целой строки (режим replace).
    Высота 1.8 * font_size — берём с запасом, чтобы descender'ы не обрезались.
    """
    height = max(font_size * 1.8, line_rect.height)
    return fitz.Rect(
        line_rect.x0,
        line_rect.y0,
        page.rect.x1 - DEFAULT_MARGIN,
        line_rect.y0 + height,
    )


def _find_same_line(page_text: dict[str, Any], rect: fitz.Rect) -> fitz.Rect | None:
    """Ищет непустую строку, y-диапазон которой пересекается с rect."""
    for block in page_text.get("blocks", []):
        for line in block.get("lines", []):
            if not line_text(line).strip():
                continue
            line_rect = fitz.Rect(line["bbox"])
            if line_rect.y0 <= rect.y1 and line_rect.y1 >= rect.y0:
                return line_rect
    return None


def _next_line_top(page_text: dict[str, Any], rect: fitz.Rect) -> float | None:
    """Возвращает y0 ближайшей непустой строки ниже rect."""
    candidates = [
        fitz.Rect(line["bbox"]).y0
        for block in page_text.get("blocks", [])
        for line in block.get("lines", [])
        if line_text(line).strip() and fitz.Rect(line["bbox"]).y0 > rect.y1
    ]
    return min(candidates) if candidates else None


def _color_from_int(value: int) -> tuple[float, float, float]:
    # PDF хранит цвет как 0xRRGGBB
    return (
        ((value >> 16) & 0xFF) / 255,
        ((value >> 8) & 0xFF) / 255,
        (value & 0xFF) / 255,
    )


def line_text(line: dict[str, Any]) -> str:
    return "".join(str(span.get("text", "")) for span in line.get("spans", []))