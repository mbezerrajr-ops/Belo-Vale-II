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


class TestTheBrincoAfterAPause:
    """Achado pelo avaliador, com ruído somado a uma gravação do titular: o
    whisper cortou o trecho entre o nome e o brinco,

        E por fim, a vaca aceitona
        117
        14 litros no total

    e o 117 sumia sem aviso — a vaca chegava sem brinco. Um número com cara
    de brinco logo depois de uma vaca que ainda não tem brinco nem litros é o
    brinco dela."""

    def test_the_brinco_on_the_next_line_is_the_cow_s(self) -> None:
        [linha] = _linhas("E por fim, a vaca aceitona\n117\n14 litros no total")

        assert (linha["brinco"], linha["nome"], linha["total"]) == ("117", "ACEITONA", "14")

    def test_after_a_full_stop_too(self) -> None:
        [linha] = _linhas("Vaca Pandora. 417. Produziu 8 litros.")

        assert (linha["brinco"], linha["nome"], linha["total"]) == ("417", "PANDORA", "8")

    def test_a_brinco_with_another_name_is_another_cow(self) -> None:
        """ "649, redonda" depois de uma vaca sem litros é outra vaca, com
        nome próprio — não o brinco da anterior."""
        linhas = _linhas("Vaca Pandora\n649, redonda, produziu 5 litros")

        assert ("649", "REDONDA", "5") in [(l["brinco"], l["nome"], l["total"]) for l in linhas]

    def test_a_cow_that_already_has_liters_does_not_take_it(self) -> None:
        linhas = _linhas("Vaca Pandora produziu 8 litros\n633\nproduziu 4 litros")

        assert [(l["brinco"], l["total"]) for l in linhas] == [(None, "8"), ("633", "4")]


class TestTheNameSaidTwice:
    """Da gravação feita pelo gravador do navegador: o whisper cortou o nome
    repetido em duas linhas,

        Pequina
        Pequina produziu

    e o primeiro "Pequina" ficava solto — virava uma observação "No áudio:
    Pequina" na vaca anterior, uma proposta inútil esperando alguém
    rejeitar. O nome repetido é o mesmo nome, com pausa ou sem."""

    def test_across_a_pause_the_repeated_name_is_one_cow(self) -> None:
        linhas = _linhas(
            "Vaca quartinha, 406\nProduziu 12 litros no total do dia\n"
            "7 pela manhã, mais 5 da tarde\nPequina\nPequina produziu\n6,5 litros\n"
            "O número de Pequina é 701"
        )

        assert [(l["brinco"], l["nome"], l["total"], l["anotacao"]) for l in linhas] == [
            ("406", "QUARTINHA", "12", None),
            ("701", "PEQUINA", "6,5", None),
        ]

    def test_the_evidence_of_the_cow_starts_at_the_first_name(self) -> None:
        [_, pequina] = _linhas("Vaca 406 produziu 12\nPequina\nPequina produziu 6,5 litros")

        assert pequina["trecho"].startswith("Pequina")
        assert pequina["trecho"].count("Pequina") == 2


class TestTheNameAfterAPause:
    """Medido com ruído forte somado: o whisper cortou cada vaca em pedaços,

        vaca 417
        Pandora
        produziu 5 litros pela manhã

    e o nome sozinho na linha virava observação ("No áudio: Pandora"). Logo
    depois do brinco, antes dos litros, uma linha só com um nome é o nome da
    vaca."""

    def test_the_name_on_its_own_line_is_the_cow_s(self) -> None:
        [linha] = _linhas("vaca 417\nPandora\nproduziu 5 litros pela manhã\n3 da tarde")

        assert (linha["brinco"], linha["nome"], linha["total"], linha["anotacao"]) == (
            "417", "PANDORA", "8", None,
        )

    def test_with_the_order_to_dry_off_nothing_is_left(self) -> None:
        texto = "a vaca 633\ngigante\nproduziu 2 litros pela manhã\nmais 2 litros à tarde\n4\ndeve ser secada depois"
        [linha] = _linhas(texto)

        assert (linha["nome"], linha["total"], linha["anotacao"]) == ("GIGANTE", "4", "secar")

    def test_a_sentence_after_the_brinco_is_not_a_name(self) -> None:
        """"Mancando da perna" não é nome: a linha continua depois da
        palavra. Vira observação, como sempre."""
        [linha] = _linhas("vaca 417\nmancando da perna\nproduziu 8 litros")

        assert linha["nome"] is None
        assert "mancando da perna" in linha["anotacao"]


class TestWhatIsNotUnderstoodIsKept:
    def test_a_command_goes_to_the_annotation(self) -> None:
        [linha] = _linhas("a 406 vai para o terceiro lote")

        assert linha["brinco"] == "406"
        assert linha["total"] is None
        assert "3º lote" in linha["anotacao"]

    def test_how_the_milk_was_divided_is_not_a_note(self) -> None:
        """"Dividida" é o jeito de dizer manhã e tarde, não informação nova."""
        [linha] = _linhas("vaca 117 deu 14 litros no total, dividida, 7 pela manhã e 7 pela noite")

        assert (linha["manha"], linha["tarde"], linha["total"], linha["anotacao"]) == ("7", "7", "14", None)

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


#: As três gravações do titular (21/09/2026), transcritas pelo whisper na
#: RX 7600 — texto exato. Os áudios ficam fora do Git; a transcrição é o que
#: o tradutor recebe.
GRAVACAO_1 = (
    ' Mensagem de teste\n'
    ' Vaca 417 Pandora\n'
    ' Produziu 5 litros pela manhã, 3 da tarde, totalizando 8 litros no total\n'
    ' A vaca 633, gigante\n'
    ' Produziu 2 litros pela manhã, mais 2 litros à tarde, 4\n'
    ' Deve ser secada depois\n'
    ' Assim como\n'
    ' Vaca 419 Viajante\n'
    ' Produziu 7 litros no total\n'
    ' Onde 3 foi pela manhã e 4 pela tarde\n'
    ' E o ideal é secar posteriormente\n'
)
GRAVACAO_2 = (
    ' Ao de teste, vaca 011, dominó, produziu 7 litros no total do dia, 4 pela manhã e 3 pela tarde, deve ser secada depois disso.\n'
    ' Vaca azeitona 117, produziu 14 litros no total.\n'
    ' Vaca sabiá produziu 10 mais 5 litros, 15, deve ir para o primeiro lote.\n'
    ' O número dela é 462, não lembro se eu falei.\n'
    ' E por fim, a vaca 389, da Agatha.\n'
    ' Produziu 4 litros pela manhã, 5 pela tarde, produzindo 9 no total.\n'
    ' E é isso.\n'
)
GRAVACAO_3 = (
    ' Bora lá, meu amigo, bora lá.\n'
    ' Áudio de teste, viu?\n'
    ' Vaca quartinha, 406, produziu 12 litros no total do dia.\n'
    ' 7 pela manhã, mais 5 da tarde.\n'
    ' Pequina, pequina produziu 6,5 litros.\n'
    ' O número de pequina é 701.\n'
    ' 649, redonda, produziu 5 litros.\n'
    ' A gente deve secar ela daqui a 7 meses.\n'
    ' 3 litros pela manhã, mais 2 da tarde.\n'
    ' 5 litros no total.\n'
    ' E por fim, a vaca aceitona, 117.\n'
    ' 14 litros no total.\n'
    ' Se é 14 litros, você já sabe quanto ela fez, né?\n'
    ' Dividido aí.\n'
    ' 7 pela manhã, mais 7 pela noite.\n'
    ' Certo? Obrigado.\n'
)


def _vacas(texto: str) -> list[tuple]:
    return [
        (l["brinco"], l["nome"], l["manha"], l["tarde"], l["total"])
        for l in speech_to_lines(texto)["linhas"]
    ]


def _eventos(texto: str) -> list[tuple]:
    extraction = lines_to_events(
        speech_to_lines(texto), extractor_name="t", extractor_version="t", origem=AUDIO_ORIGIN
    )
    return [(e.event_type, e.brinco, e.fields) for e in extraction.events if e.event_type != "production"]


class TestTheRecordingsOfTheOwner:
    """O gabarito é o que o titular ditou: 11 vacas em três gravações.

    O jeito real de falar derrubou o primeiro desenho do tradutor, que
    separava vaca por ponto final: o whisper põe ponto NO MEIO de uma vaca
    ("Vaca 417 Pandora." / "Produziu 5 litros..."), o brinco às vezes vem
    depois, em outra frase ("O número dela é 462"), e há conversa no meio
    ("Bora lá, meu amigo"). Uma vaca começa numa âncora e vai até a próxima."""

    def test_recording_1(self) -> None:
        assert _vacas(GRAVACAO_1) == [
            ("417", "PANDORA", "5", "3", "8"),
            ("633", "GIGANTE", "2", "2", "4"),
            ("419", "VIAJANTE", "3", "4", "7"),
        ]

    def test_recording_2(self) -> None:
        assert _vacas(GRAVACAO_2) == [
            ("011", "DOMINÓ", "4", "3", "7"),
            ("117", "AZEITONA", None, None, "14"),
            ("462", "SABIÁ", "10", "5", "15"),
            ("389", "AGATHA", "4", "5", "9"),
        ]

    def test_recording_3(self) -> None:
        assert _vacas(GRAVACAO_3) == [
            ("406", "QUARTINHA", "7", "5", "12"),
            ("701", "PEQUINA", None, None, "6,5"),
            ("649", "REDONDA", "3", "2", "5"),
            ("117", "ACEITONA", "7", "7", "14"),
        ]

    def test_the_commands_of_recording_1(self) -> None:
        """ "Deve ser secada depois" e "o ideal é secar posteriormente" são
        ordens de secagem — e só isso: "Assim como" e "Onde" são conversa."""
        assert _eventos(GRAVACAO_1) == [
            ("dry_off", "633", {"ordem": "secar"}),
            ("dry_off", "419", {"ordem": "secar"}),
        ]

    def test_the_commands_of_recording_2(self) -> None:
        assert _eventos(GRAVACAO_2) == [
            ("dry_off", "011", {"ordem": "secar"}),
            ("lot_change", "462", {"lote": "1"}),
        ]

    def test_the_commands_of_recording_3(self) -> None:
        """ "Secar ela daqui a 7 meses": ordem de secagem, e o prazo vira
        observação — é informação que quem revisa precisa ver. O 7 de "7
        meses" não é litro."""
        eventos = _eventos(GRAVACAO_3)

        assert eventos[0] == ("dry_off", "649", {"ordem": "secar"})
        [(tipo, brinco, campos)] = eventos[1:]
        assert (tipo, brinco) == ("note", "649")
        assert "7 meses" in campos["texto"]
