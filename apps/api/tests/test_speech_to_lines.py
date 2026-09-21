"""Da fala transcrita para as linhas de produção, sem IA.

O titular decidiu que o funcionário fala em frase natural: "a quatrocentos e
noventa e sete deu dezoito litros de manhã e quinze à tarde". O whisper
transcreve; este tradutor, código nosso, separa uma vaca da outra e acha o
brinco, a manhã, a tarde e o que mais foi dito.

Ele produz a mesma estrutura que a leitura da folha produz (uma linha por
vaca), e daí em diante o caminho é o mesmo: `lines_to_events` confere a soma,
reconhece "secar" e "lote", e a caixa de Revisão mostra tudo para aprovar.

O que não se entende NÃO se perde: vira observação com o texto falado. E
número sem brinco não vira produção de vaca nenhuma — litro inventado é pior
que texto solto.
"""

from __future__ import annotations

from app.audio.speech_to_lines import AUDIO_ORIGIN, is_phantom, speech_to_lines
from app.services.reading_to_events import lines_to_events

#: A saída real do whisper na RX 7600, em 21/09/2026, para a frase ditada.
TRANSCRITO_MEDIDO = (
    " A 497 deu 18 litros de manhã e 15 à tarde.\n"
    " A 389 deu 10 e meio de manhã e 12,5 à tarde.\n"
    " A 633 deu 2 e 2, secar.\n"
)


def _linhas(texto: str) -> list[dict]:
    return speech_to_lines(texto)["linhas"]


def _campos(linha: dict) -> tuple:
    return (linha["brinco"], linha["manha"], linha["tarde"], linha["total"])


class TestTheSentenceOfTheOwner:
    def test_as_whisper_writes_it(self) -> None:
        [linha] = _linhas("A 497 deu 18 litros de manhã e 15 à tarde.")

        assert _campos(linha) == ("497", "18", "15", "33")
        assert linha["anotacao"] is None

    def test_as_it_was_spoken_when_whisper_does_not_convert(self) -> None:
        [linha] = _linhas("a quatrocentos e noventa e sete deu dezoito litros de manhã e quinze à tarde")

        assert _campos(linha) == ("497", "18", "15", "33")

    def test_the_transcript_measured_on_the_gpu(self) -> None:
        linhas = _linhas(TRANSCRITO_MEDIDO)

        assert [_campos(linha) for linha in linhas] == [
            ("497", "18", "15", "33"),
            ("389", "10,5", "12,5", "23"),
            ("633", "2", "2", "4"),
        ]
        assert linhas[2]["anotacao"] == "secar"


class TestOneCowFromTheOther:
    def test_two_cows_in_the_same_sentence(self) -> None:
        linhas = _linhas("a 497 deu 18 e 15, a 389 deu 20")

        assert [_campos(linha) for linha in linhas] == [
            ("497", "18", "15", "33"),
            ("389", None, None, "20"),
        ]

    def test_a_loop_of_the_transcriber_is_one_cow(self) -> None:
        """Em silêncio o whisper entra em laço e repete a mesma frase. Cada
        repetição viraria uma proposta igual na caixa."""
        linhas = _linhas("A 497 deu 18 litros. " * 50)

        assert len(linhas) == 1

    def test_an_empty_transcript_has_no_lines(self) -> None:
        assert _linhas("") == []
        assert _linhas("   \n ") == []


class TestTheLiters:
    def test_a_single_number_is_the_total(self) -> None:
        """Não inventa parcela: um número só é o total do dia."""
        [linha] = _linhas("a 497 deu 33 litros")

        assert _campos(linha) == ("497", None, None, "33")

    def test_two_numbers_without_period_are_morning_and_afternoon(self) -> None:
        """ "deu dezoito e quinze": é assim que se fala no curral."""
        [linha] = _linhas("a 633 deu 2 e 2")

        assert _campos(linha) == ("633", "2", "2", "4")

    def test_the_period_word_after_the_number(self) -> None:
        [linha] = _linhas("a 497 de manhã 18, à tarde 15")

        assert _campos(linha) == ("497", "18", "15", "33")

    def test_the_total_said_out_loud(self) -> None:
        [linha] = _linhas("a 497 total 33")

        assert _campos(linha) == ("497", None, None, "33")

    def test_decimals_and_halves(self) -> None:
        [linha] = _linhas("a 389 deu dez e meio de manhã e doze vírgula cinco à tarde")

        assert _campos(linha) == ("389", "10,5", "12,5", "23")


class TestTheBrinco:
    def test_a_four_digit_brinco_written_with_a_dot(self) -> None:
        """O whisper escreve "1.015" em português. É brinco, não 1,015."""
        [linha] = _linhas("A 1.015 deu 21 litros")

        assert linha["brinco"] == "1015"

    def test_brinco_said_digit_by_digit_gets_low_confidence(self) -> None:
        """ "quatro nove sete" é 497 — mas dito assim, quem revisa precisa
        conferir: a caixa mostra "confiança baixa"."""
        [linha] = _linhas("a quatro nove sete deu dezoito")

        assert linha["brinco"] == "497"
        assert linha["confianca"] == {"brinco": 0.5}

    def test_without_brinco_the_liters_do_not_belong_to_anyone(self) -> None:
        [linha] = _linhas("deu dezoito litros de manhã")

        assert linha["brinco"] is None
        assert linha["manha"] == "18"


class TestWhatIsNotUnderstoodIsKept:
    def test_a_command_goes_to_the_annotation(self) -> None:
        [linha] = _linhas("a 406 vai para o terceiro lote")

        assert linha["brinco"] == "406"
        assert linha["total"] is None
        assert "3º lote" in linha["anotacao"]

    def test_the_rest_of_the_sentence_becomes_a_note(self) -> None:
        [linha] = _linhas("a 497 deu 18 de manhã e a bezerra da ponta curta tá mancando")

        assert linha["manha"] == "18"
        assert "bezerra da ponta curta tá mancando" in linha["anotacao"]

    def test_the_evidence_is_the_original_speech(self) -> None:
        """Quem revisa lê o que foi dito, com acento e maiúscula — não a
        versão dobrada que o código usa para comparar."""
        [linha] = _linhas("A 497 deu 18 litros de manhã e 15 à tarde.")

        assert linha["trecho"] == "A 497 deu 18 litros de manhã e 15 à tarde."


class TestPhantomPhrases:
    """Whisper em silêncio inventa frase de legenda de vídeo. Se a gravação
    inteira for só isso, não houve fala."""

    def test_known_phantoms(self) -> None:
        assert is_phantom("Legendas pela comunidade Amara.org")
        assert is_phantom(" Obrigado por assistir! ")
        assert is_phantom("")

    def test_real_speech_is_not_a_phantom(self) -> None:
        assert not is_phantom(TRANSCRITO_MEDIDO)


class TestIntoEvents:
    """Daqui em diante é o caminho da folha: o mesmo tradutor de eventos."""

    def test_production_and_dry_off_from_speech(self) -> None:
        extraction = lines_to_events(
            speech_to_lines(TRANSCRITO_MEDIDO),
            extractor_name="teste",
            extractor_version="teste",
            origem=AUDIO_ORIGIN,
        )

        tipos = [(e.event_type, e.brinco) for e in extraction.events]
        assert tipos == [
            ("production", "497"),
            ("production", "389"),
            ("production", "633"),
            ("dry_off", "633"),
        ]
        assert extraction.events[0].fields == {"producao": "33", "parcelas": "18 + 15"}

    def test_a_note_says_it_came_from_the_audio(self) -> None:
        extraction = lines_to_events(
            speech_to_lines("a 497 deu 18 e a bezerra tá mancando"),
            extractor_name="teste",
            extractor_version="teste",
            origem=AUDIO_ORIGIN,
        )

        [nota] = [e for e in extraction.events if e.event_type == "note"]
        assert nota.fields["texto"].startswith("No áudio: ")
