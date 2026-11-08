"""Bounded PDFium extraction/rendering. Original bytes are never rewritten."""
from contextlib import closing, contextmanager
import io
import math
from threading import RLock

from PIL import Image, ImageOps
import pypdfium2 as pdfium

from .contracts import MAX_IMAGE_BYTES, MAX_PAGES, MAX_PDF_BYTES, MAX_PIXELS

# PDFium is not thread-safe. This also protects concurrent API validation and
# page-preview requests; different worker processes have independent libraries.
_pdf_lock = RLock()


class InvalidDocument(ValueError):
    pass


@contextmanager
def open_pdf(body):
    with _pdf_lock:
        try:
            document = pdfium.PdfDocument(body)
        except pdfium.PdfiumError as error:
            raise InvalidDocument("PDF is damaged, encrypted or unsupported; upload an unlocked valid PDF") from None
        try:
            yield document
        finally:
            document.close()


def image_info(body):
    try:
        with Image.open(io.BytesIO(body)) as image:
            if image.format not in {"PNG", "JPEG"} or image.width * image.height > MAX_PIXELS:
                raise InvalidDocument("Use PNG/JPEG up to 30 million pixels")
            image.verify()
        with Image.open(io.BytesIO(body)) as image:
            image = ImageOps.exif_transpose(image)
            return image.width, image.height
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise InvalidDocument("Image is damaged or exceeds the allowed dimensions") from None


def inspect_document(body):
    if not body:
        raise InvalidDocument("The uploaded file is empty")
    if body[:5] == b"%PDF-":
        if len(body) > MAX_PDF_BYTES:
            raise InvalidDocument("PDF exceeds the 50 MB limit")
        with open_pdf(body) as document:
            count = len(document)
            if not 1 <= count <= MAX_PAGES:
                raise InvalidDocument("PDF must contain 1 to 500 pages")
            with closing(document[0]) as page:
                width, height = page.get_size()
                if not all(math.isfinite(value) and 0 < value <= 20000 for value in (width, height)):
                    raise InvalidDocument("PDF page dimensions are unsupported")
        return {"media_type": "application/pdf", "page_count": count}
    if body.startswith(b"\x89PNG\r\n\x1a\n") or body.startswith(b"\xff\xd8\xff"):
        if len(body) > MAX_IMAGE_BYTES:
            raise InvalidDocument("Image exceeds the 20 MB limit")
        width, height = image_info(body)
        return {"media_type": "image/png" if body[0] == 137 else "image/jpeg", "page_count": 1,
                "width": width, "height": height}
    raise InvalidDocument("Only actual PDF, PNG and JPEG files are supported; renaming an extension is not sufficient")


def extract_page(body, number, media_type):
    if media_type != "application/pdf":
        width, height = image_info(body)
        return {"width": width, "height": height, "rotation": 0, "coordinate_system": "image_top_left",
                "text": "", "blocks": [], "status": "needs_vision"}
    with open_pdf(body) as document:
        with closing(document[number - 1]) as page, closing(page.get_textpage()) as textpage:
            width, height = page.get_size()
            if not all(math.isfinite(value) and 0 < value <= 20000 for value in (width, height)):
                raise InvalidDocument("PDF page dimensions are unsupported")
            text = textpage.get_text_bounded()
            if len(text) > 200000:
                raise InvalidDocument("Page text exceeds the processing limit")
            count = textpage.count_rects()
            if count > 10000:
                raise InvalidDocument("Page layout exceeds the processing limit")
            blocks = []
            block_characters = 0
            for index in range(count):
                box = list(textpage.get_rect(index))
                if not all(math.isfinite(value) for value in box):
                    raise InvalidDocument("PDF layout contains invalid coordinates")
                value = textpage.get_text_bounded(left=box[0], bottom=box[1], right=box[2], top=box[3]).strip()
                if value:
                    block_characters += len(value)
                    if block_characters > 400000:
                        raise InvalidDocument("Page layout text exceeds the processing limit")
                    blocks.append({"bbox": box, "text": value})
            return {"width": width, "height": height, "rotation": page.get_rotation(),
                    "coordinate_system": "pdf_bottom_left", "text": text, "blocks": blocks,
                    "status": "text_ready" if len(text.strip()) >= 30 else "needs_vision"}


def render_page(body, number, media_type):
    if media_type == "application/pdf":
        with open_pdf(body) as document:
            if not 1 <= number <= len(document):
                raise InvalidDocument("Page does not exist")
            with closing(document[number - 1]) as page:
                width, height = page.get_size()
                if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                    raise InvalidDocument("Invalid page dimensions")
                scale = min(2, 1800 / max(width, height))
                with closing(page.render(scale=scale)) as bitmap:
                    image = bitmap.to_pil().convert("RGB")
    else:
        image_info(body)
        with Image.open(io.BytesIO(body)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((1800, 1800))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=88)
    image.close()
    return output.getvalue()
