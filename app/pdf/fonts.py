import tempfile
from collections.abc import Callable
from threading import Lock

import fitz

FontLoader = Callable[[], bytes | None]

_font_path_cache: dict[str, str] = {}
_cache_lock = Lock()


def resolve_font_path(
    font_name: str,
    fallback_loader: FontLoader,
) -> str:
    """
    Возвращает путь к TTF-файлу шрифта из MinIO.
    Кешируется на уровне процесса — один шрифт скачивается один раз.
    """
    with _cache_lock:
        if font_name in _font_path_cache:
            return _font_path_cache[font_name]

    font_bytes = fallback_loader()
    if not font_bytes:
        raise RuntimeError(f"Font not found in storage: {font_name}")

    path = _write_temp_font(font_bytes)

    with _cache_lock:
        _font_path_cache[font_name] = path

    return path


def _write_temp_font(font_bytes: bytes) -> str:
    # delete=False — файл нужен PyMuPDF при каждом вызове insert_textbox,
    # очищается при перезапуске контейнера
    tmp = tempfile.NamedTemporaryFile(prefix="pdf-font-", suffix=".ttf", delete=False)
    try:
        tmp.write(font_bytes)
        return tmp.name
    finally:
        tmp.close()