"""Извлечение текста из присланных документов (PDF/DOCX/TXT)."""
import io
import logging

logger = logging.getLogger("gennady.documents")

TEXT_LIMIT = 12_000  # символов в контекст из одного документа
MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 МБ — потолок Bot API download

SUPPORTED_HINT = "Пришли PDF, DOCX или текстовый файл."


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_docx(data: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)


def extract_text(data: bytes, filename: str, mime: str | None) -> tuple[str | None, str | None]:
    """(text, error). Определяет формат по расширению/типу и извлекает текст."""
    name = (filename or "").lower()
    try:
        if name.endswith(".pdf") or mime == "application/pdf":
            text = _extract_pdf(data)
        elif name.endswith(".docx") or (mime or "").endswith("wordprocessingml.document"):
            text = _extract_docx(data)
        elif name.endswith((".txt", ".md", ".csv", ".log", ".json", ".py", ".rst")) or (
            mime or ""
        ).startswith("text/"):
            text = data.decode("utf-8", errors="replace")
        else:
            return None, f"Не умею читать этот формат. {SUPPORTED_HINT}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не смог извлечь текст из %s: %s", filename, exc)
        return None, f"Не смог прочитать файл: {type(exc).__name__}"

    text = text.strip()
    if not text:
        return None, "В файле не нашлось текста (возможно, это скан без OCR)."
    if len(text) > TEXT_LIMIT:
        text = text[:TEXT_LIMIT] + "\n…(документ обрезан)"
    return text, None
