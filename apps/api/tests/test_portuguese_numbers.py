"""Número dito em português, do jeito que chega da transcrição.

O whisper converte quase tudo em algarismo ("quatrocentos e noventa e sete"
vira "497"), mas não tudo: numa frase medida em 21/09/2026, "dez e meio"
saiu "10 e meio" — algarismo com palavra. E no barulho do curral a conversão
vai falhar mais. O leitor precisa entender as três formas: algarismo, por
extenso e misturado.

A saída é sempre texto no formato brasileiro ("18", "18,5"), porque é o que o
resto do sistema já sabe ler.
"""

from __future__ import annotations

import pytest

from app.services.portuguese_numbers import parse_number


def _ler(frase: str) -> tuple[str | None, int]:
    """Lê o número no começo da frase: (valor, quantas palavras usou)."""
    return parse_number(frase.split(), 0)


class TestWrittenOut:
    @pytest.mark.parametrize(
        ("frase", "esperado"),
        [
            ("quatrocentos e noventa e sete", "497"),
            ("quatrocentos noventa e sete", "497"),
            ("cento e um", "101"),
            ("cem", "100"),
            ("dezoito", "18"),
            ("dezesseis", "16"),
            ("dezasseis", "16"),
            ("vinte e dois", "22"),
            ("mil e duzentos", "1200"),
            ("zero", "0"),
        ],
    )
    def test_the_words_become_the_number(self, frase, esperado) -> None:
        valor, usadas = _ler(frase)
        assert valor == esperado
        assert usadas == len(frase.split())


class TestHalves:
    def test_and_a_half(self) -> None:
        assert _ler("dezoito e meio") == ("18,5", 3)

    def test_and_a_half_after_digits(self) -> None:
        """Foi assim que o whisper devolveu "dez e meio" na medição real."""
        assert _ler("10 e meio") == ("10,5", 3)

    def test_meia_alone_is_not_read(self) -> None:
        """ "Meia" sozinha é 0,5 ou é 6 ("meia dúzia", ditado de número).
        Adivinhar erra o brinco, que é o erro mais caro: fica sem leitura."""
        assert _ler("meia") == (None, 0)


class TestDecimals:
    @pytest.mark.parametrize(
        ("frase", "esperado"),
        [
            ("12,5", "12,5"),
            ("12.5", "12,5"),
            ("vinte e dois vírgula cinco", "22,5"),
            ("vinte e dois ponto cinco", "22,5"),
            ("vinte e dois vírgula vinte e cinco", "22,25"),
        ],
    )
    def test_the_decimal_is_read_as_written(self, frase, esperado) -> None:
        valor, usadas = _ler(frase)
        assert valor == esperado
        assert usadas == len(frase.split())


class TestMixed:
    def test_words_and_digits_in_the_same_number(self) -> None:
        assert _ler("quatrocentos e 97") == ("497", 3)

    def test_plain_digits(self) -> None:
        assert _ler("497") == ("497", 1)

    def test_the_leading_zero_of_a_brinco_is_kept(self) -> None:
        """ "vaca 011, dominó": o brinco é 011, não 11. Numa gravação real do
        titular o whisper escreveu assim, e o cadastro guarda com o zero."""
        assert _ler("011") == ("011", 1)


class TestWhereTheNumberStops:
    def test_the_next_word_is_not_eaten(self) -> None:
        """ "dezoito litros": o número acaba em "dezoito"."""
        assert _ler("dezoito litros de manhã") == ("18", 1)

    def test_a_trailing_e_is_left_for_whoever_comes_next(self) -> None:
        """ "dezoito e quinze" são DOIS números (manhã e tarde), não um."""
        assert _ler("dezoito e quinze") == ("18", 1)

    def test_two_digits_joined_by_e_are_two_numbers(self) -> None:
        assert _ler("2 e 2") == ("2", 1)

    def test_a_word_that_is_not_a_number(self) -> None:
        assert _ler("banana") == (None, 0)

    def test_reading_from_the_middle(self) -> None:
        palavras = "a vaca quatrocentos e noventa e sete deu".split()
        assert parse_number(palavras, 2) == ("497", 5)
