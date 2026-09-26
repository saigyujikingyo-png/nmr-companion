"""Bounded reference decoding; PDFium is serialized across all HTTP threads."""

from io import BytesIO
import math
from threading import RLock
import warnings
from PIL import Image, UnidentifiedImageError
import pypdfium2 as pdfium
from .errors import NmrError

PDF_LOCK = RLock()
MAX_IMAGE_PIXELS = 16000000
PREVIEW_EDGE = 1600


def inspect_reference(data):
    if data.startswith(b"%PDF-"):
        try:
            with PDF_LOCK, pdfium.PdfDocument(data) as doc:
                count = len(doc)
                if not 1 <= count <= 1000:
                    raise NmrError("REFERENCE_LIMIT", "PDF must contain between 1 and 1000 pages.")
                page = doc[0]
                try:
                    width, height = page.get_size()
                finally:
                    page.close()
                if not all(math.isfinite(x) and 0 < x <= 20000 for x in (width, height)):
                    raise NmrError("REFERENCE_LIMIT", "PDF page dimensions are unsupported.")
                return {
                    "media_type": "application/pdf",
                    "pages": count,
                    "width": width,
                    "height": height,
                }
        except NmrError:
            raise
        except Exception as exc:
            raise NmrError(
                "REFERENCE_FORMAT",
                "PDF could not be decoded; encrypted/invalid input is unsupported.",
            ) from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as img:
                kind = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(
                    img.format
                )
                if kind is None:
                    raise NmrError(
                        "REFERENCE_FORMAT",
                        "Only PDF, PNG, JPEG and WebP reference originals are supported.",
                    )
                if not 1 <= img.width * img.height <= MAX_IMAGE_PIXELS:
                    raise NmrError("REFERENCE_LIMIT", "Reference image exceeds 16 million pixels.")
                size = img.size
                img.verify()
                return {
                    "media_type": kind,
                    "pages": 1,
                    "width": float(size[0]),
                    "height": float(size[1]),
                }
    except NmrError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Warning,
        Image.DecompressionBombError,
    ) as exc:
        raise NmrError("REFERENCE_FORMAT", "Reference image could not be safely decoded.") from exc


def reference_png(data, media_type, page_number=1):
    if media_type == "application/pdf":
        try:
            with PDF_LOCK, pdfium.PdfDocument(data) as doc:
                if not 1 <= page_number <= len(doc):
                    raise NmrError("REFERENCE_PAGE", "Reference page does not exist.")
                page = doc[page_number - 1]
                try:
                    width, height = page.get_size()
                    if not all(math.isfinite(x) and 0 < x <= 20000 for x in (width, height)):
                        raise NmrError("REFERENCE_LIMIT", "PDF page dimensions are unsupported.")
                    bitmap = page.render(scale=min(2.0, PREVIEW_EDGE / max(width, height)))
                    try:
                        img = bitmap.to_pil().copy()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
        except NmrError:
            raise
        except Exception as exc:
            raise NmrError(
                "REFERENCE_FORMAT", "The selected PDF page could not be rendered."
            ) from exc
    else:
        if page_number != 1:
            raise NmrError("REFERENCE_PAGE", "Image references contain one page.")
        inspect_reference(data)
        with Image.open(BytesIO(data)) as raw:
            raw.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE))
            img = raw.convert("RGB")
    output = BytesIO()
    img.save(output, format="PNG")
    img.close()
    return output.getvalue()
