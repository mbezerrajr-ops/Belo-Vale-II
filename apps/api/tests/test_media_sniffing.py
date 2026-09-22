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


# WebM é EBML: cada elemento é identificador + tamanho (os dois de largura
# variável) + conteúdo. É o que o Chrome grava no Android.
_EBML, _DOCTYPE, _SEGMENT = b"\x1a\x45\xdf\xa3", b"\x42\x82", b"\x18\x53\x80\x67"
_INFO, _TRACKS, _ENTRY, _TYPE = b"\x15\x49\xa9\x66", b"\x16\x54\xae\x6b", b"\xae", b"\x83"
_CLUSTER, _TAGS = b"\x1f\x43\xb6\x75", b"\x12\x54\xc3\x67"
#: "Tamanho desconhecido": o gravador ainda não sabe quanto vai gravar.
_DESCONHECIDO = b"\x01\xff\xff\xff\xff\xff\xff\xff"
_AUDIO, _VIDEO = 2, 1


def _tamanho(n: int, largura: int) -> bytes:
    """O tamanho EBML: o primeiro bit ligado marca quantos bytes ele ocupa."""
    return (n | 1 << (7 * largura)).to_bytes(largura, "big")


def _el(ident: bytes, conteudo: bytes = b"", largura: int = 8) -> bytes:
    return ident + _tamanho(len(conteudo), largura) + conteudo


def _webm(
    *tipos: int,
    doctype: bytes = b"webm",
    largura: int = 8,
    faixas_antes_do_som: bool = True,
    cauda: bytes = b"",
) -> bytes:
    """Como o Chrome grava: segmento e trechos de som com tamanho
    desconhecido, porque o gravador não sabe quando a pessoa vai parar."""
    cabecalho = _el(_EBML, _el(_DOCTYPE, doctype, largura), largura)
    faixas = _el(
        _TRACKS, b"".join(_el(_ENTRY, _el(_TYPE, bytes([t]), largura), largura) for t in tipos), largura
    )
    info = _el(_INFO, _el(b"\x2a\xd7\xb1", b"\x0f\x42\x40", largura), largura)
    trecho = _CLUSTER + _DESCONHECIDO + _el(b"\xe7", b"\x00", largura)
    corpo = info + (faixas + trecho if faixas_antes_do_som else trecho + faixas)
    return cabecalho + _SEGMENT + _DESCONHECIDO + corpo + cauda


def _pagina_ogg(pacote: bytes, *, abertura: bool = True) -> bytes:
    """Uma página Ogg com um pacote só. As páginas de abertura (BOS) trazem,
    cada uma, o cabeçalho do codec de uma faixa."""
    tipo = 0x02 if abertura else 0x00
    segmentos = [255] * (len(pacote) // 255) + [len(pacote) % 255]
    return (
        b"OggS" + bytes([0, tipo]) + b"\x00" * 8 + b"\x01\x00\x00\x00" + b"\x00" * 8
        + bytes([len(segmentos)]) + bytes(segmentos) + pacote
    )


_OPUS = b"OpusHead" + b"\x01\x01\x38\x01\x80\xbb\x00\x00\x00\x00\x00"
_VORBIS = b"\x01vorbis" + b"\x00" * 22
_THEORA = b"\x80theora" + b"\x03\x02\x01" + b"\x00" * 31


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
            (_pagina_ogg(_OPUS) + _pagina_ogg(b"OpusTags", abertura=False), "audio/ogg"),
            (_pagina_ogg(_VORBIS), "audio/ogg"),
            (b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"fmt ", "audio/wav"),
            (b"ID3" + b"\x03\x00" + b"\x00" * 10, "audio/mpeg"),
        ],
    )
    def test_the_other_formats_a_phone_may_produce(self, conteudo, esperado) -> None:
        assert sniff_media_type(conteudo) == esperado

    @pytest.mark.parametrize("marca", [b"iso5", b"iso6", b"dash", b"qt  "])
    def test_any_container_brand_is_judged_by_its_tracks(self, marca) -> None:
        """O gravador do navegador escreve MP4 fragmentado, com marca que
        nenhum gravador de celular usava ("iso5" no Chrome). A marca nunca
        decidiu nada — quem decide é a faixa lá dentro."""
        assert sniff_media_type(_mp4(marca, b"soun")) == "audio/mp4"


class TestTheRecordingMadeInTheApp:
    """Gravado no próprio app, o áudio sai no formato do navegador: WebM com
    Opus no Chrome (Android), MP4 no Safari (iPhone), Ogg no Firefox."""

    def test_the_webm_of_chrome_enters(self) -> None:
        assert sniff_media_type(_webm(_AUDIO)) == "audio/webm"

    @pytest.mark.parametrize("largura", [1, 2, 4, 8])
    def test_whatever_the_width_of_the_sizes(self, largura) -> None:
        """Cada gravador escolhe quantos bytes usar para cada tamanho."""
        assert sniff_media_type(_webm(_AUDIO, largura=largura)) == "audio/webm"

    def test_matroska_audio_enters_too(self) -> None:
        assert sniff_media_type(_webm(_AUDIO, doctype=b"matroska")) == "audio/x-matroska"

    def test_rubbish_at_the_end_does_not_hide_the_sound(self) -> None:
        assert sniff_media_type(_webm(_AUDIO, cauda=b"e2e-0f3a9c")) == "audio/webm"


class TestVideoInTheBrowserFormatsIsRefused:
    """WebM e Ogg também carregam vídeo — é o formato de vídeo da web. A
    mesma regra do MP4: a faixa de vídeo é o que denuncia."""

    def test_a_webm_with_a_video_track(self) -> None:
        assert sniff_media_type(_webm(_VIDEO, _AUDIO)) is None

    def test_a_webm_with_only_video(self) -> None:
        assert sniff_media_type(_webm(_VIDEO)) is None

    def test_a_webm_without_tracks_is_refused(self) -> None:
        assert sniff_media_type(_webm()) is None

    def test_sound_before_the_track_list_is_refused(self) -> None:
        """Sem a lista de faixas antes do primeiro trecho de som, não há como
        saber o que vem depois sem ler o arquivo inteiro."""
        assert sniff_media_type(_webm(_AUDIO, faixas_antes_do_som=False)) is None

    def test_a_webm_of_another_kind_is_refused(self) -> None:
        assert sniff_media_type(_webm(_AUDIO, doctype=b"outro")) is None

    def test_an_ogg_video(self) -> None:
        assert sniff_media_type(_pagina_ogg(_THEORA)) is None

    def test_an_ogg_video_with_sound(self) -> None:
        """Num Ogg com várias faixas, todas abrem antes de qualquer dado: dá
        para ver a de vídeo logo no começo."""
        assert sniff_media_type(_pagina_ogg(_THEORA) + _pagina_ogg(_VORBIS)) is None

    def test_an_ogg_of_nothing_known(self) -> None:
        assert sniff_media_type(b"OggS" + b"\x00" * 20) is None


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

    @pytest.mark.parametrize("corte", [4, 5, 12, 20, 40, 60])
    def test_a_webm_cut_short_is_refused_not_an_error(self, corte) -> None:
        assert sniff_media_type(_webm(_AUDIO)[:corte]) is None

    def test_an_element_of_unknown_size_that_is_not_sound_stops_the_walk(self) -> None:
        """Só o segmento e o trecho de som podem ter tamanho desconhecido. Em
        qualquer outro, não há como pular para o próximo."""
        conteudo = (
            _el(_EBML, _el(_DOCTYPE, b"webm"))
            + _SEGMENT + _DESCONHECIDO
            + _TAGS + _DESCONHECIDO + _el(_TRACKS, _el(_ENTRY, _el(_TYPE, bytes([_AUDIO]))))
        )
        assert sniff_media_type(conteudo) is None

    def test_a_webm_full_of_empty_elements_does_not_hang(self) -> None:
        vazios = _el(b"\xec") * 50_000  # elemento "Void", de enchimento
        conteudo = _el(_EBML, _el(_DOCTYPE, b"webm")) + _SEGMENT + _DESCONHECIDO + vazios
        assert sniff_media_type(conteudo) is None

    def test_an_ogg_page_cut_short(self) -> None:
        assert sniff_media_type(_pagina_ogg(_OPUS)[:30]) is None


class TestWhichReaderTheFileGoesTo:
    """O worker decide pelo tipo GRAVADO no envio, nunca pelo que o aparelho
    disse. Leitura antiga, sem tipo, continua sendo foto."""

    @pytest.mark.parametrize(
        ("media_type", "esperado"),
        [
            ("audio/mp4", "audio"),
            ("audio/webm", "audio"),
            ("audio/amr", "audio"),
            ("image/jpeg", "photo"),
            ("image/heic", "photo"),
            (None, "photo"),
            ("", "photo"),
        ],
    )
    def test_the_kind_of_reading(self, media_type, esperado) -> None:
        assert reading_kind(media_type) == esperado
