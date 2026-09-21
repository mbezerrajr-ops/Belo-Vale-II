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
from app.services.media_sniffing import sniff_image_media_type

#: Lado maior da página enviada ao leitor.
DEFAULT_MAX_SIDE = 1200

#: Quanto do alto da folha vai na pergunta do cabeçalho (data e lote).
#: 18% bastavam no PDF escaneado, em que a folha começa no pixel zero. Na foto
#: de celular a mesa entra no enquadramento e esses 18% acabavam ANTES da linha
#: "LOTE: __ DATA: __": o modelo recebia papel em branco e inventava a data.
#: Medido nas cinco fotos de 22/07, 32% enquadra todas; 45% não melhora.
HEADER_FRACTION = 0.32

#: Quanto da largura vai na pergunta dos brincos do formulário impresso: a
#: margem escrita à mão mais a coluna de números impressos, que a ancora.
LEFT_FRACTION = 0.34

#: As duas tiras que a pergunta da margem junta: a coluna dos números
#: impressos da tabela e a margem direita, onde ficam as anotações.
NUMBER_STRIP = (0.08, 0.30)
MARGIN_STRIP = (0.70, 1.0)

#: A tira estreita da segunda tentativa, colada à borda: é usada quando a
#: primeira resposta vem cheia de números, sinal de que a tira larga pegou a
#: coluna TOTAL em vez da margem.
MARGIN_STRIP_NARROW = (0.84, 1.0)

#: Sobreposição entre as faixas, para nenhuma linha cair no corte.
BAND_OVERLAP = 0.08

_PDF_MAGIC = b"%PDF"
#: Resolução de renderização do PDF (72 dpi × 3 ≈ 216 dpi) antes de reduzir.
_PDF_SCALE = 3


class UnsupportedPage(ValueError):
    """Conteúdo que não é PDF nem imagem suportada."""


def fit(page: PreprocessedImage, max_side: int) -> PreprocessedImage:
    """Reduz a página para caber no lado maior pedido. Já menor, fica como está."""
    if max(page.width, page.height) <= max_side:
        return page
    with Image.open(io.BytesIO(page.content)) as image:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        return PreprocessedImage(
            content=buffer.getvalue(), width=image.width, height=image.height, format="JPEG"
        )


def _crop(page: PreprocessedImage, box: tuple[int, int, int, int]) -> PreprocessedImage:
    with Image.open(io.BytesIO(page.content)) as image:
        cropped = image.crop(box)
        buffer = io.BytesIO()
        cropped.save(buffer, format="JPEG", quality=90)
        return PreprocessedImage(
            content=buffer.getvalue(), width=cropped.width, height=cropped.height, format="JPEG"
        )


def crop_top(page: PreprocessedImage, fraction: float = HEADER_FRACTION) -> PreprocessedImage:
    """O alto da folha, onde estão a data e o lote.

    Perguntados no meio da transcrição de 48 linhas, saíam errados; sozinhos
    num recorte, cabem numa resposta de dez palavras e com mais pixels por
    letra depois de reduzidos.
    """
    return _crop(page, (0, 0, page.width, max(1, int(page.height * fraction))))


def crop_left(page: PreprocessedImage, fraction: float = LEFT_FRACTION) -> PreprocessedImage:
    """A faixa esquerda da folha inteira, de cima a baixo.

    No formulário impresso o brinco é escrito à mão na margem esquerda, fora
    da tabela, na mesma altura do número impresso da linha. A faixa leva os
    dois: mais pixels por dígito, sem perder a âncora que diz de qual linha
    aquele brinco é.
    """
    return _crop(page, (0, 0, max(1, int(page.width * fraction)), page.height))


def crop_sides(
    page: PreprocessedImage,
    numbers: tuple[float, float] = NUMBER_STRIP,
    margin: tuple[float, float] = MARGIN_STRIP,
) -> PreprocessedImage:
    """Cola a coluna dos números das linhas ao lado da margem direita.

    Na folha as duas ficam a meia página de distância, e medindo se viu que o
    modelo lê a anotação mas erra a linha a que ela pertence: numa foto com
    setas nas linhas 5 e 14, respondeu 25 e 26. A pergunta dos brincos, onde
    as colunas já são vizinhas, acerta a sequência inteira — é a proximidade
    que ancora.

    Recortadas e coladas, as duas tiras viram uma imagem estreita em que cada
    anotação fica na mesma altura do seu número, lado a lado.
    """
    with Image.open(io.BytesIO(page.content)) as image:
        esquerda = image.crop(
            (int(image.width * numbers[0]), 0, int(image.width * numbers[1]), image.height)
        )
        direita = image.crop(
            (int(image.width * margin[0]), 0, int(image.width * margin[1]), image.height)
        )
        junta = Image.new("RGB", (esquerda.width + direita.width, image.height), "white")
        junta.paste(esquerda, (0, 0))
        junta.paste(direita, (esquerda.width, 0))
        buffer = io.BytesIO()
        junta.save(buffer, format="JPEG", quality=90)
        return PreprocessedImage(
            content=buffer.getvalue(), width=junta.width, height=junta.height, format="JPEG"
        )


def crop_bands(page: PreprocessedImage, overlap: float = BAND_OVERLAP) -> list[PreprocessedImage]:
    """Metade de cima e metade de baixo, com sobreposição.

    Recortar da página **original** (e só depois reduzir cada faixa) dá ao
    modelo o dobro de pixels por letra em relação a recortar da página já
    reduzida.
    """
    cut = int(page.height * (0.5 + overlap))
    return [
        _crop(page, (0, 0, page.width, cut)),
        _crop(page, (0, page.height - cut, page.width, page.height)),
    ]


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


def load_pages(
    content: bytes, *, max_side: int | None = DEFAULT_MAX_SIDE
) -> list[PreprocessedImage]:
    """Uma imagem por página, na ordem do arquivo.

    `max_side=None` devolve a página na resolução original — é dela que saem
    os recortes (cabeçalho, faixas), para não reduzir duas vezes.
    """
    if content.startswith(_PDF_MAGIC):
        raw_pages = _pdf_pages(content)
    elif sniff_image_media_type(content) in ("image/jpeg", "image/png"):
        raw_pages = [content]
    else:
        raise UnsupportedPage("Envie a folha como foto (JPEG ou PNG) ou PDF.")
    if not raw_pages:
        raise UnsupportedPage("O PDF não tem páginas.")
    pages = [preprocess_image(raw) for raw in raw_pages]
    return pages if max_side is None else [fit(page, max_side) for page in pages]
