from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException

from app.config import get_settings
from app.pdf import PdfFillError, fill_pdf
from app.schemas import GenerateRequest, GenerateResponse
from app.storage import FileStorage, StorageError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("pdf_creator")

app = FastAPI(title="PDF Creator")

cfg = get_settings()
storage = FileStorage(cfg)


@app.on_event("startup")
def startup() -> None:
    storage.ensure_bucket()
    log.info("minio_bucket_ready bucket=%s", cfg.minio_bucket)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    try:
        output_id = f"{cfg.output_prefix}{uuid4()}.pdf"
        log.info("generate_pdf template=%s output=%s", req.template_id, output_id)

        template = storage.read_bytes(req.template_id)
        pdf = fill_pdf(template, req.data, fallback_font=storage.read_font_bytes)
        storage.write_bytes(output_id, pdf)

        return GenerateResponse(file_id=output_id, file_url=storage.url(output_id))

    except PdfFillError as exc:
        log.warning("pdf_fill_failed: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    except StorageError as exc:
        log.exception("storage_failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    except Exception as exc:
        log.exception("generate_failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc
