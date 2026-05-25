import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.config import get_settings
from app.pdf import PdfFillError
from app.schemas import GenerateRequest, GenerateResponse
from app.services import pdf_service
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
        log.info("generate_pdf template=%s", req.template_id)

        file_id, file_url = pdf_service.generate_pdf(
            template_id=req.template_id,
            data=req.data,
            storage=storage,
            output_prefix=cfg.output_prefix,
        )
        return GenerateResponse(file_id=file_id, file_url=file_url)

    except PdfFillError as exc:
        log.warning("pdf_fill_failed: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    except StorageError as exc:
        log.exception("storage_failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc