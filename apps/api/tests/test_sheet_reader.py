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
    sheet_to_events,
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

    def test_the_prompt_tells_the_model_what_day_it_is(self) -> None:
        """Sem isso o modelo leu "25/08/2026" como 2024 na primeira folha real."""
        transport = _Transport(_reply(SHEET))
        reader = OllamaSheetReader(
            url="http://127.0.0.1:11434", model="m", post=transport, today=date(2026, 9, 19)
        )

        reader.extract(_png(), kind="photo")

        assert "19/09/2026" in transport.requests[0]["body"]["messages"][-1]["content"]

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
    """Faz o papel do Ollama: guarda o pedido e devolve a resposta dada."""

    def __init__(self, answer):
        self.answer = answer
        self.requests: list[dict] = []

    def __call__(self, url: str, body: dict, timeout: float) -> dict:
        self.requests.append({"url": url, "body": body})
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


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
        assert body["format"]["type"] == "object"
        assert len(body["messages"][-1]["images"]) == 1
        assert len(_by_type(extraction, "production")) == 5
        assert extraction.extractor_version.startswith("qwen2.5vl:7b/")

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
        answers = iter([_reply(SHEET), _reply(second)])
        reader = OllamaSheetReader(
            url="http://127.0.0.1:11434", model="m", post=lambda url, body, timeout: next(answers)
        )
        pdf = io.BytesIO()
        Image.new("RGB", (40, 30), "white").save(
            pdf, format="PDF", save_all=True, append_images=[Image.new("RGB", (40, 30), "white")]
        )

        extraction = reader.extract(pdf.getvalue(), kind="photo")

        assert extraction.reference_date == date(2026, 8, 25)
        assert _by_type(extraction, "production")[-1].brinco == "701"


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
