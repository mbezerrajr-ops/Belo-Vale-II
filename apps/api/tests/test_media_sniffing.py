"""O que a porta de entrada aceita — e o que ela recusa.

O tipo declarado pelo aparelho não vale nada: quem decide é o conteúdo. Até
a fase 2 só entrava imagem; a fase 3 abre a porta para a gravação de voz do
celular, sem afrouxar nada.

O caso que exige cuidado é o MP4: a mesma marca de contêiner ("isom",
"mp42", "3gp4") serve a um áudio de voz e a um vídeo de quinze megabytes.
Aceitar a marca e pronto deixaria o vídeo entrar e prender a GPU. Por isso o
reconhecedor entra no arquivo e olha as faixas que existem lá dentro.
"""

from __future__ import annotations

import struct

import pytest

from app.services.media_sniffing import reading_kind, sniff_media_type


def _box(kind: bytes, payload: bytes = b"") -> bytes:
    """Uma caixa ISO-BMFF: tamanho (4 bytes), tipo (4 bytes), conteúdo."""
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def _hdlr(handler: bytes) -> bytes:
    """A caixa que diz de que tipo é a faixa: 'soun' (som) ou 'vide' (vídeo)."""
    return _box(b"hdlr", b"\x00" * 8 + handler + b"\x00" * 12)


def _trak(handler: bytes) -> bytes:
    return _box(b"trak", _box(b"mdia", _hdlr(handler)))


def _mp4(brand: bytes, *handlers: bytes, cauda: bytes = b"") -> bytes:
    """Um MP4 mínimo: cabeçalho de marca e um `moov` com as faixas pedidas."""
    ftyp = _box(b"ftyp", brand + b"\x00\x00\x02\x00" + brand)
    moov = _box(b"moov", b"".join(_trak(h) for h in handlers))
    return ftyp + moov + cauda


class TestImagesStillEnter:
    """A fase 2 não pode quebrar: a foto da folha continua entrando igual."""

    @pytest.mark.parametrize(
        ("conteudo", "esperado"),
        [
            (b"\xff\xd8\xff\xe0" + b"resto", "image/jpeg"),
            (b"\x89PNG\r\n\x1a\n" + b"resto", "image/png"),
            (_mp4(b"heic"), "image/heic"),
            (_mp4(b"mif1"), "image/heic"),
        ],
    )
    def test_the_photo_formats_of_the_farm(self, conteudo, esperado) -> None:
        assert sniff_media_type(conteudo) == esperado

    def test_the_image_is_tested_first(self) -> None:
        """HEIC também é ISO-BMFF. Se o percurso de áudio viesse antes, uma
        foto de iPhone poderia sair rotulada como som."""
        assert sniff_media_type(_mp4(b"heic", b"pict")) == "image/heic"


class TestTheRecordingOfThePhone:
    @pytest.mark.parametrize("marca", [b"M4A ", b"mp42", b"isom", b"3gp4", b"3gp5"])
    def test_a_voice_recording_enters(self, marca) -> None:
        assert sniff_media_type(_mp4(marca, b"soun")) == "audio/mp4"

    @pytest.mark.parametrize(
        ("conteudo", "esperado"),
        [
            (b"#!AMR\n" + b"quadros", "audio/amr"),
            (b"#!AMR-WB\n" + b"quadros", "audio/amr-wb"),
            (b"OggS" + b"\x00" * 20, "audio/ogg"),
            (b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"fmt ", "audio/wav"),
            (b"ID3" + b"\x03\x00" + b"\x00" * 10, "audio/mpeg"),
        ],
    )
    def test_the_other_formats_a_phone_may_produce(self, conteudo, esperado) -> None:
        assert sniff_media_type(conteudo) == esperado


class TestVideoIsRefused:
    """Um vídeo de 15 MB entraria com a mesma marca de um áudio, e prenderia
    a GPU por minutos. A faixa de vídeo é o que denuncia."""

    def test_a_video_does_not_pass_as_a_recording(self) -> None:
        assert sniff_media_type(_mp4(b"mp42", b"vide", b"soun")) is None

    def test_a_container_without_a_sound_track_is_refused(self) -> None:
        assert sniff_media_type(_mp4(b"isom", b"text")) is None


class TestTheSnifferDoesNotBreak:
    """Arquivo estranho tem de virar recusa, nunca laço infinito nem exceção."""

    def test_rubbish_at_the_end_does_not_hide_the_sound(self) -> None:
        """O E2E acrescenta um identificador ao fim de cada cópia, para driblar
        a proteção contra arquivo repetido. Se isso quebrasse o percurso, o
        teste de ponta a ponta do áudio nunca passaria."""
        assert sniff_media_type(_mp4(b"M4A ", b"soun", cauda=b"e2e-0f3a9c")) == "audio/mp4"

    def test_a_box_that_says_it_goes_to_the_end_does_not_loop(self) -> None:
        # size = 0 quer dizer "até o fim do arquivo".
        conteudo = _box(b"ftyp", b"M4A \x00\x00\x02\x00") + struct.pack(">I", 0) + b"moov"
        assert sniff_media_type(conteudo) is None

    def test_a_box_that_declares_less_than_its_header_does_not_loop(self) -> None:
        conteudo = _box(b"ftyp", b"M4A \x00\x00\x02\x00") + struct.pack(">I", 3) + b"moov"
        assert sniff_media_type(conteudo) is None

    @pytest.mark.parametrize("conteudo", [b"", b"nao sou arquivo nenhum", b"\x00" * 64])
    def test_anything_else_is_refused(self, conteudo) -> None:
        assert sniff_media_type(conteudo) is None


class TestWhichReaderTheFileGoesTo:
    """O worker decide pelo tipo GRAVADO no envio, nunca pelo que o aparelho
    disse. Leitura antiga, sem tipo, continua sendo foto."""

    @pytest.mark.parametrize(
        ("media_type", "esperado"),
        [
            ("audio/mp4", "audio"),
            ("audio/amr", "audio"),
            ("image/jpeg", "photo"),
            ("image/heic", "photo"),
            (None, "photo"),
            ("", "photo"),
        ],
    )
    def test_the_kind_of_reading(self, media_type, esperado) -> None:
        assert reading_kind(media_type) == esperado
