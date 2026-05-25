from dataclasses import dataclass
from typing import Any

import fitz

PAGE_MARGIN_PT = 36  # отступ от края страницы в pt
LINE_HEIGHT_FACTOR = 1.15  # запас по высоте строки относительно font_size
MIN_FONT_SIZE = 6.0
MAX_INSERT_LINES = 4
DEFAULT_FONT_SIZE = 11.0
DEFAULT_TEXT_COLOR = (0.0, 0.0, 0.0)
DEFAULT_TEXT_COLOR_VALUE = 0


@dataclass(frozen=True)
class TextStyle:
    font_size: float
    color: tuple[float, float, float]


DEFAULT_TEXT_STYLE = TextStyle(
    font_size=DEFAULT_FONT_SIZE,
    color=DEFAULT_TEXT_COLOR,
)


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
        return DEFAULT_TEXT_STYLE

    return TextStyle(
        font_size=float(best_span.get("size") or DEFAULT_TEXT_STYLE.font_size),
        color=_color_from_int(int(best_span.get("color") or DEFAULT_TEXT_COLOR_VALUE)),
    )

# изменить
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
    line_height = _replacement_line_height(marker_rect, font_size)
    top = marker_rect.y0

    if _has_text_after_marker(page_text, marker_rect, min_gap=font_size):
        # Есть текст справа — не выходим за правую границу marker'а
        return fitz.Rect(
            marker_rect.x0,
            top,
            marker_rect.x1,
            top + line_height,
        )

    return fitz.Rect(
        marker_rect.x0,
        top,
        page.rect.x1 - PAGE_MARGIN_PT,
        _replacement_bottom(page, page_text, marker_rect, line_height),
    )


def _replacement_line_height(marker_rect: fitz.Rect, font_size: float) -> float:
    return max(font_size * LINE_HEIGHT_FACTOR, marker_rect.height)


def _has_text_after_marker(
    page_text: dict[str, Any],
    marker_rect: fitz.Rect,
    *,
    min_gap: float,
) -> bool:
    same_line_rect = _find_same_line(page_text, marker_rect)
    return same_line_rect is not None and same_line_rect.x1 > marker_rect.x1 + min_gap


def _replacement_bottom(
    page: fitz.Page,
    page_text: dict[str, Any],
    marker_rect: fitz.Rect,
    line_height: float,
) -> float:
    candidates = [
        marker_rect.y0 + line_height * MAX_INSERT_LINES,
        page.rect.y1 - PAGE_MARGIN_PT,
    ]

    next_y = _next_line_top(page_text, marker_rect)
    if next_y is not None:
        candidates.append(next_y - 1)

    return max(marker_rect.y0 + line_height, min(candidates))


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
