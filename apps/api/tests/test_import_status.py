"""Quem enviou acompanha a leitura até o fim — e sabe quando ela falhou.

Antes, o aviso "Ouvindo a gravação. As propostas aparecem aqui quando
terminar." ficava na tela para sempre, mesmo quando a leitura tinha falhado:
o funcionário saía do curral achando que estava tudo certo. E falha tem
remédios diferentes. Gravação sem fala se resolve gravando de novo, ainda com
as vacas ali. Transcritor desligado, não: a gravação está guardada, e o
"ouvir de novo" resolve depois, sem ninguém regravar nada.

Por isso a leitura que falha guarda o MOTIVO, e o envio tem um endereço para
perguntar como está.
"""

from __future__ import annotations

import asyncio
import struct
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.audio.speech_reader import SpokenEventReader
from app.audio.transcriber import (
    FakeAudioTranscriber,
    TranscriberFormatError,
    TranscriberTimeout,
    TranscriberUnavailable,
)
from app.services.event_extraction import FakeEventExtractor
from app.services.media_reading import (
    MediaReadingError,
    failure_code,
    read_upload_into_proposals,
)
from app.vision.pages import UnsupportedPage
from app.vision.sheet_reader import ReaderFormatError, ReaderTimeout, ReaderUnavailable
from app.workers.tasks import get_extraction_dispatcher
from tests.pg_support import (  # noqa: F401 — fixtures
    TEST_STORAGE,
    api,
    auth,
    database_url,
    db,
    make_farm,
    make_user,
    one,
)


def _box(kind: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def _gravacao() -> bytes:
    hdlr = _box(b"hdlr", b"\x00" * 8 + b"soun" + b"\x00" * 12)
    moov = _box(b"moov", _box(b"trak", _box(b"mdia", hdlr)))
    return _box(b"ftyp", b"M4A \x00\x00\x02\x00M4A ") + moov + uuid4().bytes


def _foto() -> bytes:
    return b"\xff\xd8\xff\xe0" + uuid4().bytes


class _Fila:
    """Faz o papel do Celery: guarda o que foi despachado, sem ler nada."""

    def __init__(self) -> None:
        self.runs: list = []

    def dispatch(self, extraction_run_id) -> None:
        self.runs.append(extraction_run_id)


class _Transcritor:
    def __init__(self, texto: str) -> None:
        self.texto = texto

    def transcribe(self, wav: bytes) -> str:
        return self.texto


class _Desligado:
    def extract(self, content: bytes, *, kind: str):
        raise TranscriberUnavailable("o transcritor não respondeu")


def _fala(texto: str | None = None) -> SpokenEventReader:
    transcritor = FakeAudioTranscriber() if texto is None else _Transcritor(texto)
    return SpokenEventReader(transcritor, decode=lambda conteudo: conteudo, model_name="falso")


@pytest.fixture()
def fila(api):  # noqa: F811
    fila = _Fila()
    api.app.dependency_overrides[get_extraction_dispatcher] = lambda: fila
    return fila


@pytest.fixture()
def envio(db, api, fila):  # noqa: F811
    """Uma fazenda, um funcionário e um jeito de enviar e de ler."""
    farm = make_farm()
    _, token = make_user("operator", "vaqueiro@belovale")

    def enviar(conteudo: bytes | None = None, nome: str = "ordenha.m4a") -> str:
        resposta = api.post(
            "/api/imports",
            data={"farm_id": farm},
            files={"file": (nome, conteudo or _gravacao(), "application/octet-stream")},
            headers=auth(token),
        )
        assert resposta.status_code == 202, resposta.text
        return resposta.json()["id"]

    def ler(leitor) -> None:
        """O passo do worker, aqui mesmo, com o leitor pedido."""

        async def run() -> None:
            engine = create_async_engine(database_url(), poolclass=NullPool)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    await read_upload_into_proposals(
                        session,
                        TEST_STORAGE,
                        {"audio": lambda: leitor, "photo": lambda: leitor},
                        extraction_run_id=fila.runs[-1],
                    )
            finally:
                await engine.dispose()

        asyncio.run(run())

    def como_esta(import_id: str):
        return api.get(f"/api/imports/{import_id}", headers=auth(token))

    return enviar, ler, como_esta


class TestRightAfterSending:
    def test_the_reading_is_waiting(self, envio) -> None:
        enviar, _, como_esta = envio

        resposta = como_esta(enviar())

        assert resposta.status_code == 200
        assert resposta.json() == {
            "id": resposta.json()["id"],
            "kind": "audio",
            "status": "pending",
            "proposals": None,
            "failure": None,
        }

    def test_the_photo_says_it_is_a_photo(self, envio) -> None:
        enviar, _, como_esta = envio

        assert como_esta(enviar(_foto(), "folha.jpg")).json()["kind"] == "photo"


class TestWhenTheReadingEnds:
    def test_it_says_how_many_proposals_came_out(self, envio) -> None:
        enviar, ler, como_esta = envio
        import_id = enviar()

        ler(_fala())

        assert como_esta(import_id).json() | {"id": None} == {
            "id": None,
            "kind": "audio",
            "status": "extracted",
            "proposals": 1,
            "failure": None,
        }

    def test_a_recording_with_no_cow_in_it_says_so(self, envio) -> None:
        """Só conversa: a leitura terminou bem, mas não há o que revisar. Quem
        enviou precisa saber agora, e não descobrir depois que nada chegou."""
        enviar, ler, como_esta = envio
        import_id = enviar()

        ler(_fala("Bora lá, meu amigo, bora lá."))

        assert como_esta(import_id).json()["proposals"] == 0

    def test_the_photo_reader_goes_the_same_way(self, envio) -> None:
        enviar, ler, como_esta = envio
        import_id = enviar(_foto(), "folha.jpg")

        ler(FakeEventExtractor())

        assert como_esta(import_id).json()["status"] == "extracted"


class TestWhenTheReadingFails:
    def test_a_transcriber_that_is_down_is_not_the_recording_s_fault(self, envio) -> None:
        enviar, ler, como_esta = envio
        import_id = enviar()

        with pytest.raises(TranscriberUnavailable):
            ler(_Desligado())

        estado = como_esta(import_id).json()
        assert (estado["status"], estado["failure"]) == ("failed", "reader_unavailable")

    def test_a_recording_without_speech_asks_for_another(self, envio) -> None:
        """Whisper sobre silêncio inventa legenda de vídeo, e o leitor recusa."""
        enviar, ler, como_esta = envio
        import_id = enviar()

        with pytest.raises(TranscriberFormatError):
            ler(_fala(" Legendas pela comunidade Amara.org"))

        estado = como_esta(import_id).json()
        assert (estado["status"], estado["failure"]) == ("failed", "unreadable")

    def test_nobody_to_answer_for_the_reading(self, envio, api) -> None:  # noqa: F811
        """A proposta nasce em nome de quem enviou; sem essa pessoa, a leitura
        não acontece. Quem pergunta agora é o dono."""
        enviar, ler, _ = envio
        import_id = enviar()
        one("DELETE FROM users WHERE email = 'vaqueiro@belovale' RETURNING id")
        _, dono = make_user("reviewer", "dono@belovale")

        with pytest.raises(MediaReadingError, match="quem enviou"):
            ler(_fala())

        estado = api.get(f"/api/imports/{import_id}", headers=auth(dono)).json()
        assert (estado["status"], estado["failure"]) == ("failed", "sender_unknown")

    def test_reading_again_shows_the_new_reading(self, envio, api) -> None:  # noqa: F811
        enviar, ler, como_esta = envio
        import_id = enviar()
        with pytest.raises(TranscriberUnavailable):
            ler(_Desligado())
        _, revisor = make_user("reviewer", "dono@belovale")

        assert api.post(f"/api/imports/{import_id}/reprocess", headers=auth(revisor)).status_code == 202

        estado = como_esta(import_id).json()
        assert (estado["status"], estado["failure"]) == ("pending", None)


class TestTryingAgain:
    """Transcritor fora do ar não é culpa de quem gravou. Antes, só um revisor
    mandava ler de novo — e o funcionário, com a gravação guardada e o aviso
    de falha na tela, não tinha o que fazer. Agora ele tenta de novo a leitura
    que FALHOU. A que deu certo continua sendo decisão de revisor: ler de novo
    criaria outra cópia de cada proposta na caixa."""

    def test_the_sender_may_try_again_a_failed_reading(self, envio, api) -> None:  # noqa: F811
        enviar, ler, como_esta = envio
        import_id = enviar()
        with pytest.raises(TranscriberUnavailable):
            ler(_Desligado())
        _, vaqueiro = make_user("operator", "outro.vaqueiro@belovale")

        resposta = api.post(f"/api/imports/{import_id}/reprocess", headers=auth(vaqueiro))

        assert resposta.status_code == 202
        assert como_esta(import_id).json()["status"] == "pending"

    def test_but_not_a_reading_that_worked(self, envio, api) -> None:  # noqa: F811
        enviar, ler, como_esta = envio
        import_id = enviar()
        ler(_fala())
        _, vaqueiro = make_user("operator", "outro.vaqueiro@belovale")

        resposta = api.post(f"/api/imports/{import_id}/reprocess", headers=auth(vaqueiro))

        assert resposta.status_code == 403
        assert resposta.json()["code"] == "reprocess_needs_reviewer"
        assert como_esta(import_id).json()["status"] == "extracted"

    def test_nor_a_reading_still_waiting(self, envio, api) -> None:  # noqa: F811
        enviar, _, _ = envio
        import_id = enviar()
        _, vaqueiro = make_user("operator", "outro.vaqueiro@belovale")

        resposta = api.post(f"/api/imports/{import_id}/reprocess", headers=auth(vaqueiro))

        assert resposta.status_code == 409
        assert resposta.json()["code"] == "import_already_processing"

    def test_a_reviewer_still_reads_again_whatever_it_is(self, envio, api) -> None:  # noqa: F811
        enviar, ler, _ = envio
        import_id = enviar()
        ler(_fala())
        _, dono = make_user("reviewer", "dono@belovale")

        assert api.post(f"/api/imports/{import_id}/reprocess", headers=auth(dono)).status_code == 202


def _interrompida(*, status: str, ha_minutos: int) -> None:
    """A leitura parou no meio: o PC reiniciou (queda de energia) ou o worker
    caiu. A tarefa já tinha saído da fila, então ninguém a termina."""
    coluna = "started_at" if status == "processing" else "created_at"
    one(
        f"UPDATE extraction_runs SET status = :st, {coluna} = now() - make_interval(mins => :m) "
        "RETURNING id",
        st=status,
        m=ha_minutos,
    )


class TestAReadingCutInTheMiddle:
    """Antes, a leitura interrompida ficava "processando" para sempre, e o
    "tentar de novo" era recusado por "ainda lendo". A mais longa medida levou
    uns 11 minutos; uma hora depois de começar, ela foi abandonada."""

    @pytest.mark.parametrize("status", ["processing", "pending"])
    def test_an_hour_later_it_shows_as_failed(self, envio, status) -> None:
        enviar, _, como_esta = envio
        import_id = enviar()
        _interrompida(status=status, ha_minutos=61)

        estado = como_esta(import_id).json()

        assert (estado["status"], estado["failure"]) == ("failed", "internal")

    def test_the_sender_may_try_it_again(self, envio, api) -> None:  # noqa: F811
        enviar, _, como_esta = envio
        import_id = enviar()
        _interrompida(status="processing", ha_minutos=61)
        _, vaqueiro = make_user("operator", "outro.vaqueiro@belovale")

        resposta = api.post(f"/api/imports/{import_id}/reprocess", headers=auth(vaqueiro))

        assert resposta.status_code == 202
        assert como_esta(import_id).json()["status"] == "pending"
        # A interrompida fica registrada como falha, não é apagada.
        assert one(
            "SELECT status, failure_code FROM extraction_runs ORDER BY created_at"
        ) == [("failed", "internal"), ("pending", None)]

    def test_a_reading_still_within_the_hour_is_still_being_read(self, envio, api) -> None:  # noqa: F811
        enviar, _, como_esta = envio
        import_id = enviar()
        _interrompida(status="processing", ha_minutos=20)
        _, vaqueiro = make_user("operator", "outro.vaqueiro@belovale")

        assert como_esta(import_id).json()["status"] == "processing"
        resposta = api.post(f"/api/imports/{import_id}/reprocess", headers=auth(vaqueiro))
        assert resposta.status_code == 409
        assert resposta.json()["code"] == "import_already_processing"


class TestTheFarmOfTheSending:
    """A fazenda é a do servidor, como em toda a aplicação monofazenda. O
    envio recebia o `farm_id` do navegador e confiava nele."""

    def test_a_sending_to_another_farm_is_refused(self, envio, api) -> None:  # noqa: F811
        _, vaqueiro = make_user("operator", "outro.vaqueiro@belovale")

        resposta = api.post(
            "/api/imports",
            data={"farm_id": str(uuid4())},
            files={"file": ("ordenha.m4a", _gravacao(), "application/octet-stream")},
            headers=auth(vaqueiro),
        )

        assert resposta.status_code == 404
        assert resposta.json()["code"] == "farm_not_found"
        assert one("SELECT count(*) FROM imports")[0][0] == 0

    def test_without_the_field_the_farm_of_the_server_is_used(self, envio, api) -> None:  # noqa: F811
        _, _, como_esta = envio
        _, vaqueiro = make_user("operator", "outro.vaqueiro@belovale")

        resposta = api.post(
            "/api/imports",
            files={"file": ("ordenha.m4a", _gravacao(), "application/octet-stream")},
            headers=auth(vaqueiro),
        )

        assert resposta.status_code == 202
        assert como_esta(resposta.json()["id"]).json()["status"] == "pending"


class TestWhoMayAsk:
    def test_an_unknown_sending_is_not_found(self, envio) -> None:
        _, _, como_esta = envio

        assert como_esta(str(uuid4())).status_code == 404

    def test_without_login_nothing_is_said(self, envio, api) -> None:  # noqa: F811
        enviar, _, _ = envio

        assert api.get(f"/api/imports/{enviar()}").status_code == 401


class TestTheReasonOfTheFailure:
    """O motivo sai do tipo do erro, e os dois leitores falam a mesma língua:
    'fora do ar' (o arquivo está bom, tente depois) ou 'ilegível' (mande
    outro)."""

    @pytest.mark.parametrize(
        ("erro", "motivo"),
        [
            (TranscriberUnavailable("desligado"), "reader_unavailable"),
            (TranscriberTimeout("demorou"), "reader_unavailable"),
            (ReaderUnavailable("desligado"), "reader_unavailable"),
            (ReaderTimeout("demorou"), "reader_unavailable"),
            (TranscriberFormatError("sem fala"), "unreadable"),
            (ReaderFormatError("não é folha"), "unreadable"),
            (UnsupportedPage("página vazia"), "unreadable"),
            (RuntimeError("qualquer outra coisa"), "internal"),
        ],
    )
    def test_each_error_has_its_reason(self, erro, motivo) -> None:
        assert failure_code(erro) == motivo

    def test_only_a_failed_reading_has_a_reason(self, envio) -> None:
        """O banco garante: motivo sem falha seria uma leitura que diz duas
        coisas ao mesmo tempo."""
        enviar, _, _ = envio
        enviar()

        with pytest.raises(Exception, match="ck_extraction_runs_failure_code"):
            one("UPDATE extraction_runs SET failure_code = 'unreadable' RETURNING id")

    def test_an_unknown_reason_is_refused(self, envio) -> None:
        enviar, _, _ = envio
        enviar()

        with pytest.raises(Exception, match="ck_extraction_runs_failure_code"):
            one("UPDATE extraction_runs SET status = 'failed', failure_code = 'azar' RETURNING id")
