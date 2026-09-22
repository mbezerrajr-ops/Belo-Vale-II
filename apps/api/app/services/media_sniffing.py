"""Que arquivo é este — pelo conteúdo, nunca pelo que o aparelho disse.

O tipo declarado no envio é dado do cliente: não vale nada. Quem decide é o
começo do arquivo. Até a fase 2 só entrava imagem; a fase 3 abre a porta
para a gravação de voz, sem afrouxar a regra.

O caso que exige cuidado é o MP4. A mesma marca de contêiner ("isom",
"mp42", "3gp4") serve a uma gravação de voz de 300 KB e a um vídeo de 15 MB
— e vídeo entrando prenderia a GPU por minutos, além de ser conteúdo que
esta plataforma não tem por que guardar. Por isso, para esses arquivos, o
reconhecedor entra e olha as faixas declaradas lá dentro: aceita se houver
som, recusa se houver vídeo.
"""

from __future__ import annotations

import struct
from typing import Literal

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}

#: Marcas de contêiner que um gravador de celular produz. Android costuma dar
#: m4a ou 3gp; iPhone dá m4a.
_AUDIO_BRANDS = {b"M4A ", b"M4B ", b"mp41", b"mp42", b"isom", b"3gp4", b"3gp5", b"3gp6", b"3g2a"}

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
        return "audio/ogg"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"ID3") or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in _AUDIO_BRANDS:
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
