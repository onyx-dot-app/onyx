import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine import get_session
from onyx.server.pdf_translator.pdf_text_translator_final import PDFTextTranslatorFinal
from onyx.utils.logger import setup_logger

logger = setup_logger()
router = APIRouter(prefix="/pdf-translator")


@router.post("/process")
async def process_pdf(
    file: UploadFile = File(...),
    _: Session = Depends(get_session),
    user=Depends(current_user),
):
    """Process a PDF file by translating its text to English."""

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=500,
            detail="PDF translation service is not configured. Please contact your administrator.",
        )

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as input_temp:
        content = await file.read()
        input_temp.write(content)
        input_temp.flush()
        input_path = input_temp.name

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as output_temp:
        output_path = output_temp.name

    try:
        logger.info(
            f"Processing PDF translation for user {user.email if user else 'anonymous'}"
        )

        processor = PDFTextTranslatorFinal()
        await processor.replace_text_in_pdf_async(input_path, output_path)

        return FileResponse(
            path=output_path,
            media_type="application/pdf",
            filename=f"translated_{file.filename}",
            headers={
                "Content-Disposition": f"attachment; filename=translated_{file.filename}"
            },
        )

    except Exception as e:
        logger.error(f"Error processing PDF: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")
    finally:
        try:
            os.unlink(input_path)
        except Exception as e:
            logger.warning(f"Failed to clean up temporary files: {e}")
