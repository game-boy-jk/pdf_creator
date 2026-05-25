import tempfile
from collections.abc import Callable
from threading import Lock

FontLoader = Callable[[], bytes]

FALLBACK_FONT_CACHE_KEY = "fallback"

_font_path_cache: dict[str, str] = {}
_cache_lock = Lock()


def resolve_font_path(
    fallback_loader: FontLoader,
) -> str:
    """
    Возвращает путь к TTF-файлу шрифта из MinIO.
    Кешируется на уровне процесса — один шрифт скачивается один раз.
    """
    with _cache_lock:
        if FALLBACK_FONT_CACHE_KEY in _font_path_cache:
            return _font_path_cache[FALLBACK_FONT_CACHE_KEY]

    font_bytes = fallback_loader()
    if not font_bytes:
        raise RuntimeError("Fallback font is empty")

    path = _write_temp_font(font_bytes)

    with _cache_lock:
        _font_path_cache[FALLBACK_FONT_CACHE_KEY] = path

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
