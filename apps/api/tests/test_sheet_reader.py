"""Leitor local de folhas de pesagem.

A folha é manuscrita: "PESAGEM DO LEITE 25/08/2026 3º LOTE" e linhas como
"3 - 389 ÁGATA → 4 + 5 = 9 → SECAR". O modelo de visão só transcreve; o que
estes testes garantem é o resto, que é código nosso:

- a transcrição vira eventos do jeito que o titular definiu (total é a
  produção, "SECAR" é ordem de secagem, "1º LOTE" é troca de lote);
- nada é inventado: campo ilegível fica vazio, linha sem número não vira
  produção;
- o leitor só fala com um endereço da própria máquina ou da rede interna —
  nunca com um provedor externo (decisão do titular);
- resposta estranha do modelo vira erro claro, não dado.
"""

from __future__ import annotations

import io
import json
from datetime import date

import pytest
from PIL import Image

from app.vision.pages import UnsupportedPage, load_pages
from app.vision.sheet_reader import (
    OllamaSheetReader,
    ReaderFormatError,
    ReaderUnavailable,
    ensure_local_url,
    incoherence,
    sheet_to_events,
    tidy_transcription,
)


def _line(seq, brinco, nome, manha, tarde, total, anotacao=None):
    return {
        "seq": seq,
        "brinco": brinco,
        "nome": nome,
        "manha": manha,
        "tarde": tarde,
        "total": total,
        "anotacao": anotacao,
        "trecho": f"{seq} - {brinco} {nome} → {manha} + {tarde} = {total} {anotacao or ''}".strip(),
    }


SHEET = {
    "data": "25/08/2026",
    "lote": "3º LOTE",
    "linhas": [
        _line("1", "853", "PRETINHA", "4", "3", "7"),
        _line("4", "016", "BELMONTE", "5,5", "4", "9,5"),
        _line("8", "633", "GIGANTE", "2", "2", "4", "SECAR"),
        _line("13", "462", "SABIÁ", "10", "5", "15", "1º LOTE"),
        _line("15", "649", "REDONDA", "3", "2", "5", "SECAR 7 MES."),
    ],
}


def _by_type(extraction, event_type):
    return [e for e in extraction.events if e.event_type == event_type]


class TestSheetToEvents:
    def test_every_line_becomes_a_production_on_the_date_of_the_header(self) -> None:
        extraction = sheet_to_events(SHEET, extractor_version="teste")

        assert extraction.reference_date == date(2026, 8, 25)
        productions = _by_type(extraction, "production")
        assert [(e.brinco, e.nome, e.fields["producao"]) for e in productions] == [
            ("853", "PRETINHA", "7"),
            ("016", "BELMONTE", "9,5"),
            ("633", "GIGANTE", "4"),
            ("462", "SABIÁ", "15"),
            ("649", "REDONDA", "5"),
        ]
        assert productions[1].fields["parcelas"] == "5,5 + 4"

    def test_the_evidence_is_the_line_as_it_was_read(self) -> None:
        extraction = sheet_to_events(SHEET, extractor_version="teste")

        first = extraction.events[0]
        assert first.evidence == {"text": SHEET["linhas"][0]["trecho"], "linha": "1"}

    def test_secar_is_a_dry_off_order(self) -> None:
        extraction = sheet_to_events(SHEET, extractor_version="teste")

        dry = _by_type(extraction, "dry_off")
        assert [e.brinco for e in dry] == ["633", "649"]
        assert all(e.fields == {"ordem": "secar"} for e in dry)

    def test_what_follows_secar_is_kept_as_a_note(self) -> None:
        """"SECAR 7 MES." — o "7 mes." não tem campo próprio; não se perde."""
        extraction = sheet_to_events(SHEET, extractor_version="teste")

        [note] = _by_type(extraction, "note")
        assert note.brinco == "649"
        assert note.fields == {"texto": "Na folha de pesagem: SECAR 7 MES."}

    def test_nth_lote_is_a_lot_change(self) -> None:
        extraction = sheet_to_events(SHEET, extractor_version="teste")

        [change] = _by_type(extraction, "lot_change")
        assert (change.brinco, change.fields) == ("462", {"lote": "1"})

    def test_an_unknown_annotation_becomes_a_note(self) -> None:
        sheet = {**SHEET, "linhas": [_line("1", "853", "PRETINHA", "4", "3", "7", "mancando")]}

        extraction = sheet_to_events(sheet, extractor_version="teste")

        assert [e.event_type for e in extraction.events] == ["production", "note"]
        assert extraction.events[1].fields == {"texto": "Na folha de pesagem: mancando"}

    def test_a_line_without_any_liters_is_not_a_production(self) -> None:
        """Nada de inventar leitura: sem total nem ordenhas, não há produção."""
        sheet = {**SHEET, "linhas": [_line("1", "853", "PRETINHA", None, None, None, "SECAR")]}

        extraction = sheet_to_events(sheet, extractor_version="teste")

        assert [e.event_type for e in extraction.events] == ["dry_off"]

    def test_missing_total_uses_nothing_and_keeps_the_milkings_for_review(self) -> None:
        sheet = {**SHEET, "linhas": [_line("1", "853", "PRETINHA", "4", "3", None)]}

        [event] = sheet_to_events(sheet, extractor_version="teste").events

        assert event.fields["producao"] is None
        assert event.fields["parcelas"] == "4 + 3"

    def test_brinco_and_name_read_in_swapped_places_are_put_back(self) -> None:
        """"18 - QUARTINHA 406": o nome veio antes do número e o modelo às vezes
        devolve os dois trocados. Número no nome e palavra no brinco é troca
        óbvia; qualquer outra combinação fica como veio."""
        sheet = {**SHEET, "linhas": [_line("18", "QUARTINHA", "406", "7", "5", "12")]}

        [event] = sheet_to_events(sheet, extractor_version="teste").events

        assert (event.brinco, event.nome) == ("406", "QUARTINHA")

    def test_two_words_are_not_swapped(self) -> None:
        sheet = {**SHEET, "linhas": [_line("1", "B2-419", "VIAJANTE", "3", "4", "7")]}

        [event] = sheet_to_events(sheet, extractor_version="teste").events

        assert (event.brinco, event.nome) == ("B2-419", "VIAJANTE")

    def test_the_prompt_does_not_suggest_a_date(self) -> None:
        """Dizer "hoje é 19/09/2026" fez o modelo escrever 19/09/2026 no
        formulário de 22/07/26. A data vem só da folha; errada, o revisor
        corrige o arquivo inteiro de uma vez."""
        transport = _Transport(_reply(SHEET))
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reader.extract(_png(), kind="photo")

        prompt = transport.requests[0]["body"]["messages"][-1]["content"]
        assert "hoje" not in prompt.lower()

    def test_empty_rows_of_the_printed_form_are_dropped(self) -> None:
        """O formulário tem 28 linhas; as que ficaram em branco não são leitura."""
        empty = {"seq": "22", "brinco": None, "nome": None, "manha": None, "tarde": None,
                 "total": None, "anotacao": None, "trecho": ""}
        sheet = {**SHEET, "linhas": [SHEET["linhas"][0], empty]}

        assert len(tidy_transcription(sheet)["linhas"]) == 1

    def test_a_row_with_only_a_margin_number_is_dropped(self) -> None:
        """Número na margem de uma linha vazia (ou riscada) não é leitura."""
        margin_only = {"seq": "24", "brinco": "6804", "nome": None, "manha": None,
                       "tarde": None, "total": None, "anotacao": None, "trecho": "6804"}
        sheet = {**SHEET, "linhas": [SHEET["linhas"][0], margin_only]}

        assert len(tidy_transcription(sheet)["linhas"]) == 1

    @pytest.mark.parametrize("tick", ["1", "/", "✓", "1."])
    def test_a_tick_beside_the_total_is_not_an_annotation(self, tick) -> None:
        """Alguém marcou "1" ao lado de cada total conferido; o modelo leu como
        anotação nas 28 linhas. Viraria 28 observações "1" na revisão."""
        sheet = {**SHEET, "linhas": [_line("1", "862", "SAIA BRANCA", "9", "8", "17", tick)]}

        [line] = tidy_transcription(sheet)["linhas"]

        assert line["anotacao"] is None

    def test_a_zero_brinco_is_no_brinco(self) -> None:
        """O modelo preencheu "0" onde não havia brinco. Zero não identifica vaca."""
        sheet = {**SHEET, "linhas": [_line("1", "0", "CHIQUINHA", "18", "20", "38")]}

        [line] = tidy_transcription(sheet)["linhas"]

        assert line["brinco"] is None

    @pytest.mark.parametrize(
        ("anotacao", "expected"),
        [
            ("→ 2º LOT", [("lot_change", {"lote": "2"})]),
            ("3º LOT", [("lot_change", {"lote": "3"})]),
            ("→ SECA", [("dry_off", {"ordem": "secar"})]),
            ("DOENTE", [("note", {"texto": "Na folha de pesagem: DOENTE"})]),
        ],
    )
    def test_margin_notes_of_the_printed_form(self, anotacao, expected) -> None:
        sheet = {**SHEET, "linhas": [_line("5", "695", "RIO NEGRO", "12", "12", "24", anotacao)]}

        events = sheet_to_events(sheet, extractor_version="teste").events

        assert [(e.event_type, e.fields) for e in events[1:]] == expected

    def test_an_illegible_header_date_stays_empty(self) -> None:
        extraction = sheet_to_events({**SHEET, "data": "2?/08"}, extractor_version="teste")

        assert extraction.reference_date is None

    def test_the_extractor_is_identified(self) -> None:
        extraction = sheet_to_events(SHEET, extractor_version="qwen2.5vl:7b/folha-v1")

        assert extraction.extractor_name == "leitor-local-folha"
        assert extraction.extractor_version == "qwen2.5vl:7b/folha-v1"


class TestOnlyLocalEndpoints:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:11434",
            "http://localhost:11434",
            "http://10.0.0.5:11434",
            "http://192.168.1.20:11434",
            "http://172.18.0.4:11434",
            "http://ollama:11434",
        ],
    )
    def test_the_machine_itself_and_the_internal_network_are_accepted(self, url) -> None:
        assert ensure_local_url(url) == url.rstrip("/")

    @pytest.mark.parametrize(
        "url",
        [
            "https://api.exemplo.com",
            "http://8.8.8.8:11434",
            "http://ollama.exemplo.com.br:11434",
            "ftp://127.0.0.1",
            "",
        ],
    )
    def test_anything_outside_is_refused(self, url) -> None:
        with pytest.raises(ValueError):
            ensure_local_url(url)


def _png(width=40, height=30) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


class _Transport:
    """Faz o papel do Ollama. Responde a pergunta do formato com `layout`, a do
    cabeçalho com `header`, e as transcrições com `answer` (uma resposta, ou
    uma lista, na ordem)."""

    def __init__(self, answer, layout="manuscrito", header=None):
        self.answers = list(answer) if isinstance(answer, list) else None
        self.answer = answer
        self.layout = layout
        self.header = header if header is not None else {"data": None, "lote": None}
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.classified = 0

    def __call__(self, url: str, body: dict, timeout: float) -> dict:
        if isinstance(self.answer, Exception):
            raise self.answer
        properties = body["format"]["properties"]
        if "formato" in properties:
            self.classified += 1
            return _reply({"formato": self.layout})
        if "linhas" not in properties:
            self.headers.append({"url": url, "body": body})
            return _reply(self.header)
        self.requests.append({"url": url, "body": body})
        answer = self.answers.pop(0) if self.answers is not None else self.answer
        if isinstance(answer, Exception):
            raise answer
        return answer


def _image_size(request: dict) -> tuple[int, int]:
    """Tamanho da imagem que foi enviada numa chamada."""
    import base64

    raw = base64.b64decode(request["body"]["messages"][-1]["images"][0])
    with Image.open(io.BytesIO(raw)) as image:
        return image.size


def _reply(content) -> dict:
    return {"message": {"content": content if isinstance(content, str) else json.dumps(content)}}


class TestOllamaSheetReader:
    def test_sends_the_page_and_the_schema_and_returns_events(self) -> None:
        transport = _Transport(_reply(SHEET))
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="qwen2.5vl:7b", post=transport)

        extraction = reader.extract(_png(), kind="photo")

        [request] = transport.requests
        assert request["url"] == "http://127.0.0.1:11434/api/chat"
        body = request["body"]
        assert body["model"] == "qwen2.5vl:7b"
        assert body["stream"] is False
        assert body["options"]["temperature"] == 0
        assert body["options"]["num_ctx"] >= 8192
        # Semente fixa: a mesma foto dá a mesma leitura de uma rodada para outra.
        assert body["options"]["seed"] == 0
        assert body["format"]["type"] == "object"
        assert len(body["messages"][-1]["images"]) == 1
        assert len(_by_type(extraction, "production")) == 5
        assert extraction.extractor_version.startswith("qwen2.5vl:7b/")

    @pytest.mark.parametrize(
        ("layout", "first_keys", "mentions"),
        [
            ("impresso", ["brinco", "numero_da_linha"], "MARGEM ESQUERDA"),
            ("manuscrito", ["numero_da_linha", "brinco"], "PESAGEM DO LEITE"),
        ],
    )
    def test_each_layout_has_its_own_instruction_and_key_order(
        self, layout, first_keys, mentions
    ) -> None:
        """O modelo preenche as chaves na ordem do esquema, da esquerda para a
        direita da folha. No formulário impresso o brinco (margem) vem antes do
        número da linha; na folha manuscrita, depois. Um esquema só para os
        dois fez um formato piorar quando o outro melhorava."""
        transport = _Transport(_reply(SHEET), layout=layout)
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reader.extract(_png(), kind="photo")

        body = transport.requests[0]["body"]
        line_schema = body["format"]["properties"]["linhas"]["items"]
        assert list(line_schema["properties"])[:2] == first_keys
        assert mentions in body["messages"][-1]["content"]
        assert transport.classified == 1

    def test_the_model_keys_become_the_internal_transcription(self) -> None:
        answer = {
            "data": "22/07/26",
            "lote": "3º",
            "linhas": [
                {"brinco": "389", "numero_da_linha": "1", "nome": "AGATA", "manha": "6",
                 "tarde": "6", "total": "12", "anotacao": None, "trecho": "389 1. AGATA 6 6 12"}
            ],
        }
        reader = OllamaSheetReader(
            url="http://127.0.0.1:11434", model="m", post=_Transport(_reply(answer))
        )

        [line] = reader.transcribe(_png())["linhas"]

        assert (line["seq"], line["brinco"]) == ("1", "389")
        assert "numero_da_linha" not in line

    def test_a_reply_that_is_not_the_schema_is_an_error(self) -> None:
        reader = OllamaSheetReader(
            url="http://127.0.0.1:11434", model="m", post=_Transport(_reply("não sei ler"))
        )

        with pytest.raises(ReaderFormatError):
            reader.extract(_png(), kind="photo")

    def test_lines_must_be_a_list(self) -> None:
        reader = OllamaSheetReader(
            url="http://127.0.0.1:11434", model="m", post=_Transport(_reply({"linhas": "x"}))
        )

        with pytest.raises(ReaderFormatError):
            reader.extract(_png(), kind="photo")

    def test_an_unreachable_reader_is_reported_as_such(self) -> None:
        reader = OllamaSheetReader(
            url="http://127.0.0.1:11434", model="m", post=_Transport(OSError("connection refused"))
        )

        with pytest.raises(ReaderUnavailable):
            reader.extract(_png(), kind="photo")

    def test_refuses_an_external_endpoint_before_sending_anything(self) -> None:
        with pytest.raises(ValueError):
            OllamaSheetReader(url="https://api.exemplo.com", model="m", post=_Transport(_reply(SHEET)))

    def test_audio_is_not_its_job(self) -> None:
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=_Transport(_reply(SHEET)))

        with pytest.raises(ValueError):
            reader.extract(b"...", kind="audio")

    def test_pages_of_a_pdf_are_read_in_order_under_the_first_header(self) -> None:
        second = {"data": None, "lote": None, "linhas": [_line("19", "701", "PIQUENA", "4,5", "2", "6,5")]}
        reader = OllamaSheetReader(
            url="http://127.0.0.1:11434", model="m", post=_Transport([_reply(SHEET), _reply(second)])
        )
        pdf = io.BytesIO()
        Image.new("RGB", (40, 30), "white").save(
            pdf, format="PDF", save_all=True, append_images=[Image.new("RGB", (40, 30), "white")]
        )

        extraction = reader.extract(pdf.getvalue(), kind="photo")

        assert extraction.reference_date == date(2026, 8, 25)
        assert _by_type(extraction, "production")[-1].brinco == "701"

    def test_each_line_carries_its_page(self) -> None:
        """Cada folha recomeça a numeração em 1; sem a página, a linha 1 de
        uma vira a linha 1 da outra na hora de comparar com o gabarito."""
        second = {"data": None, "lote": None, "linhas": [_line("1", "701", "PIQUENA", "4,5", "2", "6,5")]}
        reader = OllamaSheetReader(
            url="http://127.0.0.1:11434", model="m", post=_Transport([_reply(SHEET), _reply(second)])
        )
        pdf = io.BytesIO()
        Image.new("RGB", (40, 30), "white").save(
            pdf, format="PDF", save_all=True, append_images=[Image.new("RGB", (40, 30), "white")]
        )

        linhas = reader.transcribe(pdf.getvalue())["linhas"]

        assert [line["pagina"] for line in linhas] == [1, 1, 1, 1, 1, 2]


class TestPages:
    def test_a_scanned_pdf_becomes_one_image_per_page(self) -> None:
        pdf = io.BytesIO()
        Image.new("RGB", (400, 600), "white").save(pdf, format="PDF")

        [page] = load_pages(pdf.getvalue())

        assert page.format == "JPEG"
        assert page.content.startswith(b"\xff\xd8\xff")

    def test_large_photos_are_reduced_for_the_reader(self) -> None:
        [page] = load_pages(_png(4000, 3000), max_side=1600)

        assert max(page.width, page.height) == 1600

    def test_small_photos_are_not_enlarged(self) -> None:
        [page] = load_pages(_png(800, 600), max_side=1600)

        assert (page.width, page.height) == (800, 600)

    def test_anything_else_is_refused(self) -> None:
        with pytest.raises(UnsupportedPage):
            load_pages(b"isto nao e uma imagem")


def _dup_sheet(brinco="016"):
    """Leitura incoerente: o modelo repetiu o mesmo brinco em várias linhas."""
    return {
        "data": "22/07/26",
        "lote": "1",
        "linhas": [_line(str(i), brinco, f"VACA {i}", "5", "5", "10") for i in range(1, 6)],
    }


class TestSelfCheck:
    """O modelo às vezes entra em repetição (o mesmo brinco em várias linhas)
    ou desalinha a margem. O leitor confere a própria leitura, sem IA, e lê de
    novo em outra resolução quando ela sai incoerente."""

    def test_incoherence_counts_repeated_brincos_and_sums_that_do_not_close(self) -> None:
        sheet = {
            **SHEET,
            "linhas": [
                _line("1", "853", "PRETINHA", "4", "3", "7"),
                _line("2", "853", "ANDORINHA", "3", "4", "7"),  # brinco repetido
                _line("3", "389", "AGATA", "4", "5", "10"),  # 4 + 5 não dá 10
                _line("4", None, "SEM BRINCO", "1", "1", "2"),
                _line("5", None, "OUTRA", "1", "1", "2"),  # dois vazios não contam
            ],
        }

        assert incoherence(sheet) == 2

    def test_a_coherent_reading_is_read_only_once(self) -> None:
        transport = _Transport(_reply(SHEET))
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reader.transcribe(_png(3000, 4000))

        assert len(transport.requests) == 1

    def test_an_incoherent_reading_is_read_again_and_the_better_one_wins(self) -> None:
        transport = _Transport([_reply(_dup_sheet()), _reply(SHEET)])
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(3000, 4000))

        assert len(transport.requests) == 2
        first, second = (r["body"]["messages"][-1]["images"][0] for r in transport.requests)
        assert first != second  # outra resolução
        assert [line["brinco"] for line in reading["linhas"]] == ["853", "016", "633", "462", "649"]

    def test_a_truncated_answer_is_read_in_bands(self) -> None:
        """Folha longa: a resposta não coube no contexto e veio cortada. Em
        faixas, cada resposta é curta o bastante."""
        banda = {"data": "25/08/26", "lote": "1º", "linhas": [_line("1", "853", "PRETINHA", "4", "3", "7")]}
        transport = _Transport([_reply("{\"linhas\": [{\"brinco\""), _reply(banda), _reply(banda)])
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(3000, 4000))

        assert len(transport.requests) == 3
        assert [line["seq"] for line in reading["linhas"]] == ["1"]

    def test_two_truncated_answers_are_an_error(self) -> None:
        transport = _Transport([_reply("{\"linhas\": [{"), _reply("{\"linhas\": [{")])
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        with pytest.raises(ReaderFormatError):
            reader.transcribe(_png(3000, 4000))

    def test_a_long_sheet_that_times_out_is_read_in_bands(self) -> None:
        """A folha do 1º lote tem 48 linhas: a resposta inteira não sai dentro
        do tempo. Lida em duas faixas com sobreposição, cada resposta é curta;
        as linhas se juntam pelo número impresso."""
        topo = {"data": "25/08/26", "lote": "1º", "linhas": [
            _line("1", "853", "PRETINHA", "4", "3", "7"),
            _line("2", "694", "ANDORINHA", "3", "4", "7"),
        ]}
        fundo = {"data": None, "lote": None, "linhas": [
            _line("2", "694", "ANDORINHA", "3", "4", "7"),  # sobreposição
            _line("3", "389", "AGATA", "4", "5", "9"),
        ]}
        transport = _Transport([TimeoutError("tempo"), _reply(topo), _reply(fundo)])
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(1200, 1600))

        assert [line["seq"] for line in reading["linhas"]] == ["1", "2", "3"]
        assert reading["data"] == "25/08/26"
        # A página inteira, depois cada faixa.
        assert len(transport.requests) == 3
        alturas = [len(r["body"]["messages"][-1]["images"][0]) for r in transport.requests]
        assert alturas[1] != alturas[0] and alturas[2] != alturas[0]

    def test_bands_that_also_fail_are_reported(self) -> None:
        transport = _Transport([TimeoutError("tempo"), TimeoutError("tempo")])
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        with pytest.raises(ReaderUnavailable):
            reader.transcribe(_png(1200, 1600))

    def test_when_both_are_incoherent_the_less_incoherent_wins(self) -> None:
        worse = _dup_sheet()
        better = {**_dup_sheet(), "linhas": _dup_sheet()["linhas"][:3]}
        transport = _Transport([_reply(worse), _reply(better)])
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(3000, 4000))

        assert len(reading["linhas"]) == 3


class TestHeaderInItsOwnCall:
    """A data e o lote saíam no meio da transcrição de 48 linhas, disputando
    atenção com o resto — e saíam errados: numa folha de 25/08 o cabeçalho
    do 2º lote foi lido como "3º LOTE" em duas leituras seguidas, e todas as
    47 linhas daquela página deixaram de casar com o gabarito. Agora o topo
    da folha vai numa chamada própria, curta e com mais pixels por letra."""

    def test_the_header_is_asked_apart_from_the_lines(self) -> None:
        transport = _Transport(_reply(SHEET), header={"data": "25/08/2026", "lote": "2º LOTE"})
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(1200, 1600))

        assert len(transport.headers) == 1
        # O que vale é o cabeçalho lido à parte, não o que veio na transcrição.
        assert (reading["data"], reading["lote"]) == ("25/08/2026", "2º LOTE")

    def test_the_header_call_sees_only_the_top_of_the_page(self) -> None:
        transport = _Transport(_reply(SHEET), header={"data": "25/08/2026", "lote": "2º"})
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reader.transcribe(_png(1200, 1600))

        _, altura_topo = _image_size(transport.headers[0])
        _, altura_pagina = _image_size(transport.requests[0])
        assert altura_topo < altura_pagina

    def test_an_unreadable_header_keeps_what_the_page_said(self) -> None:
        """Sem cabeçalho legível no recorte, o que a transcrição trouxe vale."""
        transport = _Transport(_reply(SHEET), header={"data": None, "lote": None})
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(1200, 1600))

        assert (reading["data"], reading["lote"]) == (SHEET["data"], SHEET["lote"])


class TestBandResolution:
    def test_bands_are_cropped_from_the_original_page_not_from_the_reduced_one(self) -> None:
        """A faixa recortada da página já reduzida tem metade dos pixels por
        letra. Recortada do original e só então reduzida, cada faixa chega ao
        modelo com o dobro de resolução útil."""
        banda = {"data": None, "lote": None, "linhas": [_line("1", "853", "PRETINHA", "4", "3", "7")]}
        transport = _Transport([TimeoutError("tempo"), _reply(banda), _reply(banda)])
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reader.transcribe(_png(3000, 4000))

        largura_pagina, _ = _image_size(transport.requests[0])
        largura_banda, _ = _image_size(transport.requests[1])
        assert largura_banda > largura_pagina
