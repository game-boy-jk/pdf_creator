from __future__ import annotations

import tempfile
from collections.abc import Callable
from threading import Lock

import fitz

# Шрифты, встроенные в PyMuPDF — для них не нужен файл на диске
BUILTIN_FONTS = {"helv", "Helvetica", "Times-Roman", "Courier", "arial-narrow"}
_cache_lock = Lock()

FontLoader = Callable[[], bytes | None]

# Кеш живёт на уровне процесса: ключ — имя шрифта в PDF,
# значение — путь к temp-файлу или None если шрифт не нашли
_font_path_cache: dict[str, str | None] = {}
_cache_lock = Lock()


def resolve_font_path(
    font_name: str,
    document: fitz.Document,
    page: fitz.Page,
    fallback_loader: FontLoader | None,
) -> str | None:
    """
    Возвращает путь к TTF-файлу для font_name или None если хватает встроенного.

    Порядок поиска:
    1. Встроенные шрифты PyMuPDF — файл не нужен
    2. Процессный кеш — чтобы не извлекать один шрифт при каждом запросе
    3. Fallback из S3 (PDF_FONT_OBJECT_KEY) — для кириллицы и subset-шрифтов
    4. Шрифт, вложенный в сам PDF
    """
    if font_name in BUILTIN_FONTS:
        return None

    with _cache_lock:
        if font_name in _font_path_cache:
            return _font_path_cache[font_name]

    font_bytes = _load_font_bytes(font_name, document, page, fallback_loader)

    path = _write_temp_font(font_bytes) if font_bytes else None

    with _cache_lock:
        _font_path_cache[font_name] = path

    return path


def _load_font_bytes(
    font_name: str,
    document: fitz.Document,
    page: fitz.Page,
    fallback_loader: FontLoader | None,
) -> bytes | None:
    if fallback_loader is not None:
        data = fallback_loader()
        if data:
            return data

    return _extract_embedded_font(document, page, font_name)


def _extract_embedded_font(
    document: fitz.Document,
    page: fitz.Page,
    target_font: str,
) -> bytes | None:
    """
    Извлекает шрифт из PDF по имени.
    Если в документе ровно один шрифт — возвращает его без проверки имени:
    это нормальная ситуация для PDF с subset-шрифтами вида 'ABCDEF+FontName'.
    """
    all_fonts: list[bytes] = []

    for font_entry in page.get_fonts(full=True):
        xref = int(font_entry[0])
        base_name = str(font_entry[3])

        extracted = document.extract_font(xref)
        font_bytes = extracted[3] or None

        if not font_bytes:
            continue

        all_fonts.append(font_bytes)

        # Subset-шрифты в PDF имеют вид "ABCDEF+OriginalName"
        if base_name == target_font or base_name.endswith(f"+{target_font}") or base_name.endswith(target_font):
            return font_bytes

    if len(all_fonts) == 1:
        return all_fonts[0]

    return None


def _write_temp_font(font_bytes: bytes) -> str:
    # delete=False — файл нужен PyMuPDF при каждом вызове insert_textbox,
    # очищается через atexit или перезапуск контейнера
    tmp = tempfile.NamedTemporaryFile(prefix="pdf-font-", suffix=".ttf", delete=False)
    try:
        tmp.write(font_bytes)
        return tmp.name
    finally:
        tmp.close()