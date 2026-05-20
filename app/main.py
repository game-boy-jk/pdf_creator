from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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

cfg = get_settings()
storage = FileStorage(cfg)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    storage.ensure_bucket()
    log.info("minio_bucket_ready bucket=%s", cfg.minio_bucket)
    yield


app = FastAPI(title="PDF Creator", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    try:
        output_id = f"{cfg.output_prefix}{uuid4()}.pdf"
        log.info("generate_pdf template=%s output=%s", req.template_id, output_id)

        template = storage.read_bytes(req.template_id)
        pdf = fill_pdf(
            template,
            req.data,
            replace=req.replace,
            fallback_font=storage.read_font_bytes,
        )
        storage.write_bytes(output_id, pdf)

        return GenerateResponse(file_id=output_id, file_url=storage.url(output_id))

    except PdfFillError as exc:
        log.warning("pdf_fill_failed: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    except StorageError as exc:
        log.exception("storage_failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
