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

from app.vision.pages import UnsupportedPage, crop_left, crop_sides, crop_top, load_pages
from app.vision.sheet_reader import (
    MARGIN_PROMPT,
    drop_margin_runs,
    PROMPTS,
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

    @pytest.mark.parametrize("vazio", ["null", "NULL", "none", "N/A", "-", "--"])
    def test_the_word_null_written_out_is_not_a_reading(self, vazio) -> None:
        """O modelo às vezes escreve a PALAVRA "null" em vez de deixar o campo
        vazio. Numa foto real ele a escreveu nas 14 linhas em branco do
        formulário, e elas viraram 14 produções fantasma com litros "null"."""
        escrita = {"seq": "15", "brinco": vazio, "nome": vazio, "manha": vazio,
                   "tarde": vazio, "total": vazio, "anotacao": vazio, "trecho": vazio}
        sheet = {**SHEET, "linhas": [SHEET["linhas"][0], escrita]}

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
            # O apelido que o Docker dá ao hospedeiro: é assim que o worker
            # em contêiner alcança o Ollama rodando no Windows, fora dele.
            "http://host.docker.internal:11434",
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

    def __init__(self, answer, layout="manuscrito", header=None, margin=None, brincos=None):
        self.answers = list(answer) if isinstance(answer, list) else None
        self.answer = answer
        self.layout = layout
        self.header = header if header is not None else {"data": None, "lote": None}
        self.margin = margin if margin is not None else {"anotacoes": []}
        self.brincos = brincos if brincos is not None else {"brincos": []}
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.margins: list[dict] = []
        self.left: list[dict] = []
        self.classified = 0

    def __call__(self, url: str, body: dict, timeout: float) -> dict:
        if isinstance(self.answer, Exception):
            raise self.answer
        properties = body["format"]["properties"]
        if "formato" in properties:
            self.classified += 1
            return _reply({"formato": self.layout})
        if "brincos" in properties:
            self.left.append({"url": url, "body": body})
            if isinstance(self.brincos, Exception):
                raise self.brincos
            return _reply(self.brincos)
        if "anotacoes" in properties:
            self.margins.append({"url": url, "body": body})
            if isinstance(self.margin, Exception):
                raise self.margin
            if isinstance(self.margin, list):
                return _reply(self.margin[min(len(self.margins) - 1, len(self.margin) - 1)])
            return _reply(self.margin)
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

    def test_the_header_crop_clears_the_desk_around_a_phone_photo(self) -> None:
        """18% do alto enquadravam o cabeçalho no PDF escaneado, em que a folha
        começa no pixel zero. Na foto de celular esses 18% são a mesa e a borda
        do papel: o corte caía EM CIMA da linha "LOTE: __ DATA: __", o modelo
        recebia um retângulo em branco e inventava a data — três das cinco
        fotos de 22/07 saíram com 25/08, e com elas a folha inteira. Medido nas
        cinco, 32% enquadra todas; 45% não melhora."""
        [page] = load_pages(_png(1000, 1400), max_side=None)

        topo = crop_top(page)

        assert topo.height >= page.height * 0.30

    def test_the_two_sides_of_the_sheet_are_glued_into_one_narrow_image(self) -> None:
        """A anotação fica na margem direita e o número da linha, a meia folha
        de distância, na esquerda. Perguntando sobre a página inteira, o modelo
        lia a anotação mas errava a linha: numa foto com setas nas linhas 5, 6
        e 14, respondeu 25 e 26 — linhas em branco. Coladas as duas tiras, cada
        anotação fica ao lado do seu número."""
        [page] = load_pages(_png(1000, 1400), max_side=None)

        junta = crop_sides(page)

        assert junta.height == page.height
        # O miolo da folha (as colunas de litros) fica de fora: a pergunta é
        # só sobre número e margem.
        assert junta.width < page.width * 0.6

    def test_the_left_strip_keeps_the_brinco_column_and_its_line_numbers(self) -> None:
        """No formulário impresso o brinco fica na margem esquerda, à mesma
        altura do número impresso da linha. Recortar essa faixa dá mais pixels
        por dígito sem perder a âncora: o número que diz de qual linha é."""
        [page] = load_pages(_png(1000, 1400), max_side=None)

        faixa = crop_left(page)

        assert faixa.height == page.height  # a folha inteira, de cima a baixo
        assert faixa.width < page.width


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


class TestRepeatedAnnotation:
    """A anotação fica na margem, longe da linha, e o modelo às vezes copia a
    mesma para a folha inteira: numa foto real, uma seta "→ 3º LOTE" virou 23
    trocas de lote, e um "SECA" virou 27 ordens de secagem. Uma ordem de secar
    falsa é o erro mais caro que pode chegar na caixa, então a folha inteira
    marcada igual é recusada — a leitura crua fica guardada no run, e quem
    revisa tem a foto ao lado."""

    def test_the_same_annotation_on_the_whole_page_is_dropped(self) -> None:
        sheet = {
            **SHEET,
            "linhas": [
                _line(str(i), f"10{i}", f"VACA {i}", "5", "5", "10", "3º LOTE")
                for i in range(1, 12)
            ],
        }

        tidy = tidy_transcription(sheet)

        assert [line["anotacao"] for line in tidy["linhas"]] == [None] * 11
        # A produção não se perde: o que é suspeito é a margem, não a tabela.
        assert [line["total"] for line in tidy["linhas"]] == ["10"] * 11

    def test_an_annotation_on_a_few_lines_is_kept(self) -> None:
        linhas = [
            _line(str(i), f"10{i}", f"VACA {i}", "5", "5", "10") for i in range(1, 12)
        ]
        linhas[0] = _line("1", "101", "VACA 1", "5", "5", "10", "3º LOTE")
        linhas[4] = _line("5", "105", "VACA 5", "5", "5", "10", "3º LOTE")
        linhas[9] = _line("10", "110", "VACA 10", "5", "5", "10", "DOENTE")

        tidy = tidy_transcription({**SHEET, "linhas": linhas})

        anotadas = [line["anotacao"] for line in tidy["linhas"] if line["anotacao"]]
        assert anotadas == ["3º LOTE", "3º LOTE", "DOENTE"]

    def test_a_short_page_where_every_cow_really_moved_is_kept(self) -> None:
        # Quatro linhas marcadas iguais cabem na realidade (um lote pequeno
        # que mudou junto); vinte e três, não.
        linhas = [
            _line(str(i), f"10{i}", f"VACA {i}", "5", "5", "10", "SECAR")
            for i in range(1, 5)
        ]

        tidy = tidy_transcription({**SHEET, "linhas": linhas})

        assert [line["anotacao"] for line in tidy["linhas"]] == ["SECAR"] * 4

    def test_accents_and_case_do_not_hide_the_repetition(self) -> None:
        textos = ["3º LOTE", "3o lote", "3º Lote", "3º LOTE", "3o LOTE", "3º lote"]
        linhas = [
            _line(str(i), f"10{i}", f"VACA {i}", "5", "5", "10", texto)
            for i, texto in enumerate(textos, start=1)
        ]

        tidy = tidy_transcription({**SHEET, "linhas": linhas})

        assert [line["anotacao"] for line in tidy["linhas"]] == [None] * 6


class TestMarginInItsOwnCall:
    """A anotação fica solta na margem direita, longe da linha a que pertence,
    e no meio da transcrição o modelo a copiava para a folha inteira: numa
    foto real uma seta "→ 3º LOTE" virou 23 trocas de lote. A guarda contra
    repetição apaga o estrago, mas com ele some também a anotação verdadeira.

    Então a margem é perguntada sozinha — como já se faz com o cabeçalho —,
    e a resposta é curta: só as linhas que têm escrita."""

    def test_the_margin_is_asked_apart_from_the_lines(self) -> None:
        transport = _Transport(_reply(SHEET), layout="impresso")
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reader.transcribe(_png(1200, 1600))

        assert len(transport.margins) == 1

    def test_what_the_margin_call_says_wins_over_the_lines(self) -> None:
        linhas = [
            _line("1", "101", "UMA", "5", "5", "10", "SECAR"),
            _line("2", "102", "OUTRA", "5", "5", "10", "SECAR"),
            _line("3", "103", "TERCEIRA", "5", "5", "10", "SECAR"),
        ]
        transport = _Transport(
            _reply({**SHEET, "linhas": linhas}),
            layout="impresso",
            margin={"anotacoes": [{"linha": "2", "texto": "3º LOTE"}]},
        )
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(1200, 1600))

        assert [linha["anotacao"] for linha in reading["linhas"]] == [None, "3º LOTE", None]

    def test_an_empty_margin_clears_what_the_lines_invented(self) -> None:
        linhas = [_line(str(i), f"10{i}", f"VACA {i}", "5", "5", "10", "SECAR") for i in range(1, 4)]
        transport = _Transport(
            _reply({**SHEET, "linhas": linhas}), layout="impresso", margin={"anotacoes": []}
        )
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(1200, 1600))

        assert [linha["anotacao"] for linha in reading["linhas"]] == [None, None, None]

    def test_a_margin_call_that_fails_keeps_what_the_lines_said(self) -> None:
        """Sem a resposta da margem, o que a transcrição trouxe continua
        valendo — com a guarda contra repetição ainda no caminho."""
        linhas = [_line("1", "101", "UMA", "5", "5", "10", "SECAR")]
        transport = _Transport(
            _reply({**SHEET, "linhas": linhas}),
            layout="impresso",
            margin=ReaderUnavailable("leitor fora do ar"),
        )
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(1200, 1600))

        assert [linha["anotacao"] for linha in reading["linhas"]] == ["SECAR"]


class TestBrincosFromTheLeftStrip:
    """No formulário impresso o brinco é escrito à mão na margem esquerda,
    fora da tabela — é o campo que mais erra, e um dígito trocado não tem
    contexto que o denuncie. A faixa esquerda vai numa chamada própria: só
    a coluna de brincos e os números impressos que os ancoram, com o dobro
    de pixels por dígito."""

    def test_the_left_strip_is_asked_only_for_the_printed_form(self) -> None:
        impresso = _Transport(_reply(SHEET), layout="impresso")
        manuscrito = _Transport(_reply(SHEET), layout="manuscrito")

        for transport in (impresso, manuscrito):
            reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)
            reader.transcribe(_png(1200, 1600))

        assert (len(impresso.left), len(manuscrito.left)) == (1, 0)

    def test_what_the_left_strip_says_replaces_the_brinco(self) -> None:
        linhas = [_line("1", "323", "CHIQUINHA", "18", "20", "38")]
        transport = _Transport(
            _reply({**SHEET, "linhas": linhas}),
            layout="impresso",
            brincos={"brincos": [{"linha": "1", "brinco": "923"}]},
        )
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(1200, 1600))

        assert reading["linhas"][0]["brinco"] == "923"

    def test_a_line_the_strip_does_not_name_keeps_what_was_read(self) -> None:
        """Diferente da margem: aqui o problema é dígito trocado, não anotação
        inventada. Linha que a faixa não cita fica com o que a transcrição
        trouxe."""
        linhas = [
            _line("1", "323", "CHIQUINHA", "18", "20", "38"),
            _line("2", "586", "GAUCELA", "19", "23", "42"),
        ]
        transport = _Transport(
            _reply({**SHEET, "linhas": linhas}),
            layout="impresso",
            brincos={"brincos": [{"linha": "2", "brinco": "586"}]},
        )
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(1200, 1600))

        assert [linha["brinco"] for linha in reading["linhas"]] == ["323", "586"]

    def test_a_strip_call_that_fails_keeps_what_was_read(self) -> None:
        linhas = [_line("1", "323", "CHIQUINHA", "18", "20", "38")]
        transport = _Transport(
            _reply({**SHEET, "linhas": linhas}),
            layout="impresso",
            brincos=ReaderUnavailable("leitor fora do ar"),
        )
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(1200, 1600))

        assert reading["linhas"][0]["brinco"] == "323"

    def test_the_handwritten_sheet_has_no_margin_to_ask_about(self) -> None:
        """Ali a anotação vem no fim da própria linha ("→ SECAR"), não numa
        margem. Perguntar pela margem devolveria lista vazia — e apagaria a
        anotação verdadeira."""
        linhas = [_line("1", "633", "GIGANTE", "2", "2", "4", "SECAR")]
        transport = _Transport(_reply({**SHEET, "linhas": linhas}), layout="manuscrito")
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(1200, 1600))

        assert transport.margins == []
        assert reading["linhas"][0]["anotacao"] == "SECAR"

    def test_the_prompt_does_not_dictate_which_annotations_exist(self) -> None:
        """A instrução dizia o que procurar: "→ 2º LOTE", "→ SECA", "DOENTE".
        O modelo devolveu as três — numa folha que só tem duas setas, ambas
        de lote. Exemplo dentro do prompt vira resposta; o que a folha tem,
        quem diz é a folha."""
        for texto in (MARGIN_PROMPT, PROMPTS["impresso"]):
            assert "SECA" not in texto.upper()
            assert "DOENTE" not in texto.upper()
        # A folha manuscrita continua com "SECAR" no exemplo que ensina o
        # FORMATO da linha ("8 - 633 GIGANTE → 2 + 2 = 4 → SECAR"), e ali a
        # leitura de anotação estava razoável. Tirar sem medir seria trocar um
        # erro conhecido por um desconhecido: está na fila, com gabarito.
        assert "SECAR" in PROMPTS["manuscrito"]

    def test_the_line_number_matches_even_written_with_a_dot(self) -> None:
        """O formulário imprime "6." e o modelo devolve o ponto junto. Casar
        exatamente não colaria a anotação em linha nenhuma."""
        linhas = [_line("6", "586", "GAUCELA", "19", "23", "42")]
        transport = _Transport(
            _reply({**SHEET, "linhas": linhas}),
            layout="impresso",
            margin={"anotacoes": [{"linha": "6.", "texto": "2º LOTE"}]},
        )
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(1200, 1600))

        assert reading["linhas"][0]["anotacao"] == "2º LOTE"

    def test_the_brinco_line_number_also_matches_with_a_dot(self) -> None:
        linhas = [_line("1", "999", "CHIQUINHA", "18", "20", "38")]
        transport = _Transport(
            _reply({**SHEET, "linhas": linhas}),
            layout="impresso",
            brincos={"brincos": [{"linha": "1.", "brinco": "323"}]},
        )
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(1200, 1600))

        assert reading["linhas"][0]["brinco"] == "323"


class TestAnnotationSpelling:
    """O "º" da folha sai do modelo como ":", "o" ou ".". A troca de lote não
    pode virar observação só por causa disso — na caixa de Revisão uma é um
    campo preenchido, a outra é texto solto para alguém ler."""

    @pytest.mark.parametrize("escrito", ["2º LOT", "2: LOT", "2o LOTE", "2. LOTE", "2 LOTE", "2= LOT", "2- LOTE"])
    def test_a_lot_change_survives_how_the_degree_sign_was_read(self, escrito) -> None:
        sheet = {**SHEET, "linhas": [_line("1", "323", "CHIQUINHA", "18", "20", "38", escrito)]}

        extraction = sheet_to_events(sheet, extractor_version="teste")

        tipos = [e.event_type for e in extraction.events]
        assert tipos == ["production", "lot_change"], escrito
        assert extraction.events[1].fields == {"lote": "2"}


class TestMarginRuns:
    """A margem lida à parte ainda inventa, e a invenção tem assinatura:
    linhas SEGUIDAS com o mesmo texto. Numa folha real o modelo listou as
    linhas 21 a 27 com "3º LOT" — o rabo em branco do formulário — junto com
    duas anotações verdadeiras. Anotação de verdade é esparsa: as seis dessa
    folha estavam nas linhas 2, 8, 10, 11, 13 e 20."""

    def test_a_run_of_equal_annotations_is_dropped(self) -> None:
        lidas = {str(linha): "3º LOT" for linha in range(21, 28)}
        lidas["8"] = "3º LOT"

        assert drop_margin_runs(lidas) == {"8": "3º LOT"}

    def test_scattered_equal_annotations_are_kept(self) -> None:
        lidas = {"2": "3º LOT", "8": "3º LOT", "10": "3º LOT", "13": "1º LOT"}

        assert drop_margin_runs(lidas) == lidas

    def test_a_short_run_is_kept(self) -> None:
        """Duas ou três vacas vizinhas mudando de lote juntas acontece."""
        lidas = {"5": "2º LOT", "6": "2º LOT", "7": "2º LOT"}

        assert drop_margin_runs(lidas) == lidas

    def test_a_run_of_different_texts_is_kept(self) -> None:
        lidas = {"5": "2º LOT", "6": "DOENTE", "7": "SECA", "8": "1º LOT"}

        assert drop_margin_runs(lidas) == lidas


class TestMarginReadTheWrongColumn:
    """A tira da direita é uma fração fixa da largura, e cada foto enquadra a
    folha de um jeito: numa delas a tira caiu sobre a coluna TOTAL, e o modelo
    respondeu 26, 34, 33, 30 — os litros, não anotações.

    Resposta feita de números é sinal de coluna errada, e a folha é perguntada
    de novo numa tira mais estreita, colada à borda direita."""

    def test_an_answer_made_of_numbers_is_asked_again_closer_to_the_edge(self) -> None:
        numeros = {"anotacoes": [{"linha": str(i), "texto": str(20 + i)} for i in range(1, 6)]}
        anotacoes = {"anotacoes": [{"linha": "5", "texto": "2º LOTE"}]}
        transport = _Transport(_reply(SHEET), layout="impresso", margin=[numeros, anotacoes])
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(1200, 1600))

        assert len(transport.margins) == 2
        # A segunda pergunta vê uma tira mais estreita que a primeira.
        primeira, _ = _image_size(transport.margins[0])
        segunda, _ = _image_size(transport.margins[1])
        assert segunda < primeira
        assert [linha["anotacao"] for linha in reading["linhas"]][0] is None

    def test_an_answer_with_words_is_not_asked_again(self) -> None:
        transport = _Transport(
            _reply(SHEET),
            layout="impresso",
            margin={"anotacoes": [{"linha": "5", "texto": "2º LOTE"}]},
        )
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reader.transcribe(_png(1200, 1600))

        assert len(transport.margins) == 1

    def test_if_the_narrow_strip_also_answers_numbers_nothing_is_annotated(self) -> None:
        numeros = {"anotacoes": [{"linha": str(i), "texto": str(20 + i)} for i in range(1, 6)]}
        transport = _Transport(_reply(SHEET), layout="impresso", margin=[numeros, numeros])
        reader = OllamaSheetReader(url="http://127.0.0.1:11434", model="m", post=transport)

        reading = reader.transcribe(_png(1200, 1600))

        assert all(linha["anotacao"] is None for linha in reading["linhas"])
