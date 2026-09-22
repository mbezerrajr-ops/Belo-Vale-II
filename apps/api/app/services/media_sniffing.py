"""Que arquivo é este — pelo conteúdo, nunca pelo que o aparelho disse.

O tipo declarado no envio é dado do cliente: não vale nada. Quem decide é o
começo do arquivo. Até a fase 2 só entrava imagem; a fase 3 abre a porta
para a gravação de voz, sem afrouxar a regra.

O caso que exige cuidado são os contêineres. A mesma marca de MP4
("isom", "mp42", "3gp4") serve a uma gravação de voz de 300 KB e a um vídeo
de 15 MB — e vídeo entrando prenderia a GPU por minutos, além de ser conteúdo
que esta plataforma não tem por que guardar. O mesmo vale para WebM e Ogg,
que são os formatos de vídeo da web e também o que o navegador produz ao
gravar voz dentro do app. Por isso, para esses arquivos, o reconhecedor entra
e olha as faixas declaradas lá dentro: aceita se houver som, recusa se houver
vídeo.
"""

from __future__ import annotations

import struct
from typing import Literal

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}

#: Quantas caixas o percurso visita antes de desistir. Arquivo bem formado de
#: celular tem dezenas; um número alto aqui só serve a arquivo hostil.
_MAX_BOXES = 10_000

#: Caixas que contêm outras caixas no caminho até saber o tipo da faixa.
_CONTAINER_BOXES = {b"moov", b"trak", b"mdia"}


def sniff_image_media_type(data: bytes) -> str | None:
    """JPEG, PNG ou HEIC pelos bytes iniciais. Outra coisa: `None`."""
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS:
        return "image/heic"
    return None


def sniff_media_type(data: bytes) -> str | None:
    """O tipo do arquivo enviado, ou `None` se não for coisa que se aceite.

    Imagem é testada primeiro: HEIC também é ISO-BMFF, e uma foto de iPhone
    não pode sair rotulada como som.
    """
    if (image := sniff_image_media_type(data)) is not None:
        return image
    if data.startswith(b"#!AMR-WB\n"):
        return "audio/amr-wb"
    if data.startswith(b"#!AMR\n"):
        return "audio/amr"
    if data.startswith(b"OggS"):
        return "audio/ogg" if _ogg_is_audio(data) else None
    if data.startswith(_EBML):
        return _webm_media_type(data)
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"ID3") or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    # A marca do MP4 não decide nada: o gravador do navegador escreve
    # "iso5", que nenhum gravador de celular usava. Quem decide é a faixa.
    if len(data) >= 12 and data[4:8] == b"ftyp":
        handlers = _track_handlers(data)
        if b"vide" in handlers:
            return None  # é vídeo com a mesma marca; não é o que se pede aqui
        if b"soun" in handlers:
            return "audio/mp4"
    return None


def reading_kind(media_type: str | None) -> Literal["photo", "audio"]:
    """Para qual leitor o arquivo vai, pelo tipo GRAVADO no envio.

    Leitura antiga, gravada antes de existir áudio, tem tipo de imagem ou
    nenhum: continua sendo foto.
    """
    return "audio" if (media_type or "").startswith("audio/") else "photo"


def _track_handlers(data: bytes) -> set[bytes]:
    """Que faixas o arquivo declara: `soun`, `vide`, `text`...

    Percorre as caixas de topo até `moov`, desce até `hdlr` e lê o tipo. O
    `moov` de gravação de celular costuma vir no fim do arquivo, então o
    percurso vai até o fim — com guardas para não travar em arquivo
    corrompido ou hostil.
    """
    handlers: set[bytes] = set()
    _walk(data, 0, len(data), handlers, [0])
    return handlers


def _walk(data: bytes, start: int, end: int, handlers: set[bytes], visited: list[int]) -> None:
    position = start
    while position + 8 <= end:
        visited[0] += 1
        if visited[0] > _MAX_BOXES:
            return
        size = struct.unpack(">I", data[position : position + 4])[0]
        kind = data[position + 4 : position + 8]
        body = position + 8
        if size == 1:  # tamanho de 64 bits, logo depois do tipo
            if body + 8 > end:
                return
            size = struct.unpack(">Q", data[body : body + 8])[0]
            body += 8
        elif size == 0:  # "até o fim do arquivo"
            size = end - position
        if size < body - position:  # caixa menor que o próprio cabeçalho
            return
        stop = min(position + size, end)
        if kind == b"hdlr" and body + 12 <= stop:
            # Na `hdlr`, o tipo da faixa vem depois de versão+bandeiras e de
            # um campo reservado.
            handlers.add(data[body + 8 : body + 12])
        elif kind in _CONTAINER_BOXES:
            _walk(data, body, stop, handlers, visited)
        position += size


# ------------------------------------------------------------------- Ogg

#: Cabeçalhos de codec de som que abrem uma faixa Ogg: Opus (Firefox e as
#: notas de voz), Vorbis, Speex e FLAC.
_OGG_AUDIO = (b"OpusHead", b"\x01vorbis", b"Speex   ", b"\x7fFLAC")
#: Faixa de índice, que não é som nem vídeo.
_OGG_NEUTRAL = (b"fishead\x00",)
_OGG_MAX_STREAMS = 64


def _ogg_is_audio(data: bytes) -> bool:
    """Toda faixa do Ogg abre numa página própria (BOS), e todas as páginas de
    abertura vêm antes de qualquer dado. Basta olhar essas: som entra; vídeo
    (Theora) ou coisa desconhecida, não."""
    position, audio = 0, 0
    for _ in range(_OGG_MAX_STREAMS):
        if not data.startswith(b"OggS", position) or position + 27 > len(data):
            break
        if not data[position + 5] & 0x02:  # acabaram as páginas de abertura
            break
        count = data[position + 26]
        table = data[position + 27 : position + 27 + count]
        body = position + 27 + count
        if len(table) < count:
            return False
        if any(data.startswith(codec, body) for codec in _OGG_AUDIO):
            audio += 1
        elif not any(data.startswith(neutral, body) for neutral in _OGG_NEUTRAL):
            return False
        position = body + sum(table)
    return audio > 0


# ------------------------------------------------------------ WebM / EBML

_EBML = b"\x1a\x45\xdf\xa3"
_DOCTYPE = b"\x42\x82"
_SEGMENT = b"\x18\x53\x80\x67"
_TRACKS = b"\x16\x54\xae\x6b"
_TRACK_ENTRY = b"\xae"
_TRACK_TYPE = b"\x83"
_CLUSTER = b"\x1f\x43\xb6\x75"
_TRACK_VIDEO, _TRACK_AUDIO = 1, 2
_DOCTYPES = {b"webm": "audio/webm", b"matroska": "audio/x-matroska"}


def _webm_media_type(data: bytes) -> str | None:
    """WebM (o que o Chrome grava) ou Matroska: aceita se as faixas forem só de
    som.

    O gravador do navegador não sabe quanto a pessoa vai falar, então escreve
    o segmento e os trechos de som com tamanho "desconhecido". A lista de
    faixas vem antes do primeiro trecho — e é só até ela que se lê.
    """
    header = _ebml_element(data, 0)
    if header is None or header.ident != _EBML or header.unknown:
        return None
    doctype = next(
        (data[c.body : c.end] for c in _ebml_children(data, header) if c.ident == _DOCTYPE), None
    )
    if doctype not in _DOCTYPES:
        return None
    segment = _ebml_element(data, header.end)
    if segment is None or segment.ident != _SEGMENT:
        return None
    types = _track_types(data, segment)
    if not types or _TRACK_VIDEO in types or _TRACK_AUDIO not in types:
        return None
    return _DOCTYPES[doctype]


class _Element:
    __slots__ = ("ident", "body", "end", "unknown")

    def __init__(self, ident: bytes, body: int, end: int, unknown: bool) -> None:
        self.ident, self.body, self.end, self.unknown = ident, body, end, unknown


def _ebml_element(data: bytes, position: int) -> _Element | None:
    """O elemento que começa em `position`, ou `None` se estiver cortado ou
    malformado. Identificador e tamanho têm largura variável: o primeiro bit
    ligado diz quantos bytes cada um ocupa."""
    if position >= len(data):
        return None
    width = _vint_width(data[position], 4)
    if width is None or position + width >= len(data):
        return None
    ident = data[position : position + width]
    at = position + width
    size_width = _vint_width(data[at], 8)
    if size_width is None or at + size_width > len(data):
        return None
    raw = int.from_bytes(data[at : at + size_width], "big")
    value = raw & ((1 << (7 * size_width)) - 1)
    body = at + size_width
    if value == (1 << (7 * size_width)) - 1:  # todos os bits ligados: "desconhecido"
        return _Element(ident, body, len(data), unknown=True)
    return _Element(ident, body, min(body + value, len(data)), unknown=False)


def _vint_width(first: int, limit: int) -> int | None:
    for width in range(1, limit + 1):
        if first & (0x80 >> (width - 1)):
            return width
    return None


def _ebml_children(data: bytes, parent: _Element, visited: list[int] | None = None):
    visited = visited if visited is not None else [0]
    position = parent.body
    while position < parent.end:
        visited[0] += 1
        if visited[0] > _MAX_BOXES:
            return
        child = _ebml_element(data, position)
        if child is None or child.end > parent.end:
            return
        yield child
        if child.unknown:
            return  # não há como saber onde acaba; quem chamou decide
        position = child.end


def _track_types(data: bytes, segment: _Element) -> set[int] | None:
    """Os tipos das faixas (1 vídeo, 2 som...), ou `None` se o som começar
    antes da lista de faixas."""
    visited = [0]
    for child in _ebml_children(data, segment, visited):
        if child.ident == _TRACKS:
            types: set[int] = set()
            for entry in _ebml_children(data, child, visited):
                if entry.ident != _TRACK_ENTRY:
                    continue
                for field in _ebml_children(data, entry, visited):
                    if field.ident == _TRACK_TYPE and field.body < field.end:
                        types.add(int.from_bytes(data[field.body : field.end], "big"))
            return types
        if child.ident == _CLUSTER or child.unknown:
            return None
    return None
