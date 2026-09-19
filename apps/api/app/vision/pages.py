"""Páginas para o leitor: PDF escaneado ou foto → imagens prontas para ler.

A folha chega como foto do celular (JPEG/PNG) ou como PDF de scanner, que é
só uma imagem por página. Cada página passa pelo pré-processamento de sempre
(rotação do EXIF, contraste) e é reduzida para o leitor: o modelo de visão
não lê melhor uma foto de 4000 px, só mais devagar e com mais memória.
"""

from __future__ import annotations

import io

import pypdfium2 as pdfium
from PIL import Image

from app.services.image_preprocessing import PreprocessedImage, preprocess_image
from app.services.image_sniffing import sniff_image_media_type

#: Lado maior da página enviada ao leitor.
DEFAULT_MAX_SIDE = 1200

_PDF_MAGIC = b"%PDF"
#: Resolução de renderização do PDF (72 dpi × 3 ≈ 216 dpi) antes de reduzir.
_PDF_SCALE = 3


class UnsupportedPage(ValueError):
    """Conteúdo que não é PDF nem imagem suportada."""


def _fit(page: PreprocessedImage, max_side: int) -> PreprocessedImage:
    if max(page.width, page.height) <= max_side:
        return page
    with Image.open(io.BytesIO(page.content)) as image:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        return PreprocessedImage(
            content=buffer.getvalue(), width=image.width, height=image.height, format="JPEG"
        )


def _pdf_pages(content: bytes) -> list[bytes]:
    try:
        document = pdfium.PdfDocument(content)
    except pdfium.PdfiumError as error:
        raise UnsupportedPage(f"PDF ilegível: {error}") from error
    try:
        images = []
        for index in range(len(document)):
            rendered = document[index].render(scale=_PDF_SCALE).to_pil()
            buffer = io.BytesIO()
            rendered.convert("RGB").save(buffer, format="PNG")
            images.append(buffer.getvalue())
        return images
    finally:
        document.close()


def load_pages(content: bytes, *, max_side: int = DEFAULT_MAX_SIDE) -> list[PreprocessedImage]:
    """Uma imagem por página, na ordem do arquivo."""
    if content.startswith(_PDF_MAGIC):
        raw_pages = _pdf_pages(content)
    elif sniff_image_media_type(content) in ("image/jpeg", "image/png"):
        raw_pages = [content]
    else:
        raise UnsupportedPage("Envie a folha como foto (JPEG ou PNG) ou PDF.")
    if not raw_pages:
        raise UnsupportedPage("O PDF não tem páginas.")
    return [_fit(preprocess_image(raw), max_side) for raw in raw_pages]
