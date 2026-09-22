"""A nota do ouvido: gravações conferidas, comparadas vaca a vaca pelo brinco.

A folha tem número de linha; a fala não. Por isso a comparação é pelo brinco
dito: uma vaca omitida não desalinha as outras. E a nota separa o que falta
do que chega ERRADO, porque os dois custos são muito diferentes: vaca que
falta não chega à Revisão; vaca com brinco ou total trocado chega, com cara
de certa, esperando alguém aprovar.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import pytest

from app.audio.transcriber import TranscriberUnavailable
from app.core.evaluate_transcriber import compare_cows, main, snr_db
from tests.test_speech_to_lines import GRAVACAO_1

GABARITO_1 = {
    "linhas": [
        {"brinco": "417", "nome": "PANDORA", "manha": "5", "tarde": "3", "total": "8"},
        {"brinco": "633", "nome": "GIGANTE", "manha": "2", "tarde": "2", "total": "4", "secar": True},
        {"brinco": "419", "nome": "VIAJANTE", "manha": "3", "tarde": "4", "total": "7", "secar": True},
    ]
}


def _nota(texto: str, gabarito: dict = GABARITO_1):
    return compare_cows(texto, gabarito)


class TestCowByCow:
    def test_the_recording_of_the_owner_is_all_right(self) -> None:
        nota = _nota(GRAVACAO_1)

        assert (nota.expected, nota.right, nota.missing, nota.wrong) == (3, 3, [], [])
        assert (nota.dry_off_expected, nota.dry_off_found, nota.commands_invented) == (2, 2, 0)

    def test_a_total_heard_wrong_is_a_wrong_reading(self) -> None:
        nota = _nota(GRAVACAO_1.replace("totalizando 8 litros", "totalizando 9 litros"))

        assert nota.right == 2
        assert [(e.brinco, e.field, e.expected, e.read) for e in nota.wrong] == [
            ("417", "total", "8", "9")
        ]

    def test_a_brinco_heard_wrong_is_missing_and_wrong(self) -> None:
        """Medido: sem marcas de tempo, o whisper ouviu "4162" em vez de
        "462". A vaca certa falta, e chega uma vaca que não foi dita."""
        nota = _nota(GRAVACAO_1.replace("Vaca 419", "Vaca 4119"))

        assert nota.missing == ["419"]
        assert [(e.brinco, e.field) for e in nota.wrong] == [("4119", "brinco")]

    def test_a_cow_skipped_by_the_transcriber_is_only_missing(self) -> None:
        """O salto de marca de tempo: a vaca some, e nada chega errado."""
        inicio = GRAVACAO_1.index("Vaca 419")
        nota = _nota(GRAVACAO_1[:inicio])

        assert nota.missing == ["419"]
        assert nota.wrong == []

    def test_name_and_milkings_are_counted_apart(self) -> None:
        """O total é o que vira produção; nome e ordenhas ajudam quem revisa."""
        nota = _nota(GRAVACAO_1)

        assert (nota.name_right, nota.milkings_right) == (3, 3)

    def test_a_dry_off_order_nobody_gave(self) -> None:
        gabarito = {"linhas": [dict(linha, secar=False) for linha in GABARITO_1["linhas"]]}

        assert _nota(GRAVACAO_1, gabarito).commands_invented == 2

    def test_a_lot_change_is_compared_too(self) -> None:
        texto = "Vaca 462 sabiá produziu 10 mais 5 litros, 15, deve ir para o primeiro lote."
        gabarito = {"linhas": [{"brinco": "462", "total": "15", "lote": "1"}]}

        nota = _nota(texto, gabarito)

        assert (nota.lot_expected, nota.lot_found) == (1, 1)


def _wav(amostras: list[int], taxa: int = 16_000) -> bytes:
    corpo = struct.pack(f"<{len(amostras)}h", *amostras)
    return (
        b"RIFF" + struct.pack("<I", 36 + len(corpo)) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, taxa, taxa * 2, 2, 16)
        + b"data" + struct.pack("<I", len(corpo)) + corpo
    )


class TestTheNoiseLabel:
    def test_the_signal_to_noise_ratio_is_measured_not_guessed(self) -> None:
        voz = [int(8_000 * math.sin(n / 5)) for n in range(16_000)]
        ruido = [800 if n % 2 else -800 for n in range(16_000)]
        misturado = [v + r for v, r in zip(voz, ruido)]

        # RMS da voz ~5657, do ruído 800: 20·log10(5657/800) ≈ 17 dB.
        assert snr_db(_wav(voz), _wav(misturado)) == pytest.approx(17.0, abs=0.2)


class _Ouvido:
    def __init__(self, texto: str) -> None:
        self.texto = texto
        self.ouviu: list[bytes] = []

    def __call__(self, wav: bytes) -> str:
        self.ouviu.append(wav)
        return self.texto


def _pasta(tmp_path: Path, *, com_gabarito: bool = True) -> Path:
    (tmp_path / "ordenha.m4a").write_bytes(b"m4a de verdade")
    if com_gabarito:
        (tmp_path / "ordenha.gabarito.json").write_text(json.dumps(GABARITO_1), encoding="utf-8")
    return tmp_path


def _main(tmp_path: Path, *args: str, ouvido=None, **kwargs) -> int:
    return main(
        ["--samples", str(tmp_path), *args],
        transcribe=ouvido or _Ouvido(GRAVACAO_1),
        decode=lambda conteudo: b"wav:" + conteudo,
        model="ouvido-de-teste",
        **kwargs,
    )


class TestTheCommand:
    def test_it_scores_and_saves_what_was_heard(self, tmp_path, capsys) -> None:
        pasta = _pasta(tmp_path)

        assert _main(pasta) == 0

        saida = capsys.readouterr().out
        assert "3/3 vacas certas" in saida
        salvo = json.loads((pasta / "ordenha.transcricao.json").read_text(encoding="utf-8"))
        assert salvo["texto"] == GRAVACAO_1
        leitura = json.loads((pasta / "ordenha.leitura.json").read_text(encoding="utf-8"))
        assert [e["brinco"] for e in leitura["events"] if e["event_type"] == "production"] == [
            "417", "633", "419",
        ]

    def test_the_converted_recording_is_what_is_heard(self, tmp_path) -> None:
        ouvido = _Ouvido(GRAVACAO_1)

        _main(_pasta(tmp_path), ouvido=ouvido)

        assert ouvido.ouviu == [b"wav:m4a de verdade"]

    def test_reuse_does_not_listen_again(self, tmp_path) -> None:
        """Mexer no tradutor não precisa de GPU: a transcrição salva basta."""
        pasta = _pasta(tmp_path)
        _main(pasta)
        ouvido = _Ouvido("nada")

        assert _main(pasta, "--reuse", ouvido=ouvido) == 0
        assert ouvido.ouviu == []

    def test_with_noise_each_level_is_heard_and_saved_apart(self, tmp_path, capsys) -> None:
        pasta = _pasta(tmp_path)
        ouvido = _Ouvido(GRAVACAO_1)

        _main(
            pasta,
            "--ruido",
            "0.08",
            ouvido=ouvido,
            add_noise=lambda wav, nivel: wav + f"+ruido {nivel}".encode(),
            measure=lambda limpo, sujo: 17.0,
        )

        assert ouvido.ouviu == [b"wav:m4a de verdade", b"wav:m4a de verdade+ruido 0.08"]
        assert (pasta / "ordenha.ruido-0.08.transcricao.json").exists()
        saida = capsys.readouterr().out
        assert "voz/ruído 17 dB" in saida
        assert "sintético" in saida

    def test_a_recording_without_gabarito_is_left_out(self, tmp_path, capsys) -> None:
        assert _main(_pasta(tmp_path, com_gabarito=False)) == 2
        assert "Nenhuma gravação" in capsys.readouterr().err

    def test_a_transcriber_that_is_down_stops_everything(self, tmp_path, capsys) -> None:
        def desligado(wav: bytes) -> str:
            raise TranscriberUnavailable("o transcritor não respondeu em http://127.0.0.1:8081")

        assert _main(_pasta(tmp_path), ouvido=desligado) == 2
        assert "não respondeu" in capsys.readouterr().err
