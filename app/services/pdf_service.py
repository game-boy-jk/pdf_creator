import logging
from uuid import uuid4

from app.pdf import fill_pdf
from app.storage import FileStorage

log = logging.getLogger(__name__)


def generate_pdf(
    template_id: str,
    data: dict[str, str],
    storage: FileStorage,
    output_prefix: str,
) -> tuple[str, str]:
    """
    Читает шаблон, заполняет данными, сохраняет результат.
    Возвращает (file_id, file_url).
    """
    output_id = f"{output_prefix}{uuid4()}.pdf"
    log.info("generate_pdf template=%s output=%s", template_id, output_id)

    template = storage.read_bytes(template_id)
    pdf = fill_pdf(template, data, fallback_font=storage.read_font_bytes)
    storage.write_bytes(output_id, pdf)

    return output_id, storage.url(output_id)