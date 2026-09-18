"""Proteção do login contra força bruta.

Exposta na internet pública, a tela de login é varrida por bots. Sem limite de
tentativas, a senha de um funcionário é adivinhável por repetição.

O limite é por conta **e** por origem: limitar só por conta permitiria varrer
muitas contas de um mesmo IP, e limitar só por IP puniria a fazenda inteira
quando todos saem pelo mesmo endereço.

As mesmas regras valem para as duas implementações. A de memória serve a um
processo só; a do Redis é compartilhada entre réplicas e sobrevive a um
reinício da API. Os testes do Redis rodam contra um servidor real quando
`REDIS_URL` está definido.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.login_throttle import (
    LOCKOUT_SECONDS,
    MAX_ATTEMPTS,
    InMemoryLoginThrottle,
    RedisLoginThrottle,
    ResilientLoginThrottle,
)


def _at(seconds: float) -> datetime:
    return datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc) + timedelta(
        seconds=seconds
    )


def run(coroutine):
    return asyncio.run(coroutine)


class _Bound:
    """Adapta a interface assíncrona para os testes síncronos.

    Cada chamada roda num event loop próprio; o cliente Redis é criado dentro
    dele, porque uma conexão assíncrona fica presa ao loop que a abriu.
    """

    def __init__(self, factory) -> None:
        self._factory = factory

    def _call(self, method: str, *args, **kwargs):
        async def go():
            throttle = self._factory()
            try:
                return await getattr(throttle, method)(*args, **kwargs)
            finally:
                close = getattr(throttle, "aclose", None)
                if close is not None:
                    await close()

        return run(go())

    def check(self, *args, **kwargs):
        return self._call("check", *args, **kwargs)

    def record_failure(self, *args, **kwargs):
        return self._call("record_failure", *args, **kwargs)

    def record_success(self, *args, **kwargs):
        return self._call("record_success", *args, **kwargs)


def _memory():
    shared = InMemoryLoginThrottle()
    return _Bound(lambda: shared)


def _redis():
    url = os.getenv("REDIS_URL")
    if not url:
        pytest.skip("REDIS_URL is required for Redis integration tests")
    # Prefixo único por teste: nenhum teste enxerga o contador de outro, e
    # nada aqui toca chaves de uso real.
    prefix = f"bv2-test:{uuid.uuid4().hex}:"
    return _Bound(lambda: RedisLoginThrottle.from_url(url, prefix=prefix))


@pytest.fixture(params=["memory", "redis"])
def throttle(request):
    return _memory() if request.param == "memory" else _redis()


class TestFailureCounting:
    def test_allows_attempts_below_the_limit(self, throttle) -> None:
        for index in range(MAX_ATTEMPTS - 1):
            assert throttle.check("joao@belovale", "10.0.0.1", now=_at(index)) is None
            throttle.record_failure("joao@belovale", "10.0.0.1", now=_at(index))

        assert throttle.check("joao@belovale", "10.0.0.1", now=_at(99)) is None

    def test_blocks_after_reaching_the_limit(self, throttle) -> None:
        for index in range(MAX_ATTEMPTS):
            throttle.record_failure("joao@belovale", "10.0.0.1", now=_at(index))

        retry_after = throttle.check("joao@belovale", "10.0.0.1", now=_at(MAX_ATTEMPTS))
        assert retry_after is not None
        assert retry_after > 0

    def test_failures_at_the_same_instant_all_count(self, throttle) -> None:
        """Uma rajada de bot chega no mesmo milissegundo: cada tentativa
        conta, mesmo com o mesmo horário."""
        for _ in range(MAX_ATTEMPTS):
            throttle.record_failure("joao@belovale", "10.0.0.1", now=_at(0))

        assert throttle.check("joao@belovale", "10.0.0.1", now=_at(1)) is not None

    def test_success_clears_the_counter(self, throttle) -> None:
        for index in range(MAX_ATTEMPTS - 1):
            throttle.record_failure("joao@belovale", "10.0.0.1", now=_at(index))
        throttle.record_success("joao@belovale", "10.0.0.1")

        assert throttle.check("joao@belovale", "10.0.0.1", now=_at(50)) is None

    def test_lockout_expires(self, throttle) -> None:
        for index in range(MAX_ATTEMPTS):
            throttle.record_failure("joao@belovale", "10.0.0.1", now=_at(index))

        assert throttle.check("joao@belovale", "10.0.0.1", now=_at(1)) is not None
        assert (
            throttle.check(
                "joao@belovale", "10.0.0.1", now=_at(LOCKOUT_SECONDS + 60)
            )
            is None
        )


class TestScoping:
    def test_blocking_one_account_does_not_block_another(self, throttle) -> None:
        for index in range(MAX_ATTEMPTS):
            throttle.record_failure("joao@belovale", "10.0.0.1", now=_at(index))

        assert throttle.check("maria@belovale", "10.0.0.2", now=_at(10)) is None

    def test_same_account_from_another_origin_is_also_blocked(self, throttle) -> None:
        """Trocar de IP não pode zerar o bloqueio de uma conta sob ataque."""
        for index in range(MAX_ATTEMPTS):
            throttle.record_failure("joao@belovale", "10.0.0.1", now=_at(index))

        assert throttle.check("joao@belovale", "203.0.113.9", now=_at(10)) is not None

    def test_one_origin_attacking_many_accounts_is_blocked(self, throttle) -> None:
        """Varrer muitas contas de um mesmo IP também é força bruta."""
        for index in range(MAX_ATTEMPTS):
            throttle.record_failure(f"conta{index}@belovale", "203.0.113.9", now=_at(index))

        assert throttle.check("outra@belovale", "203.0.113.9", now=_at(50)) is not None

    def test_success_does_not_clear_the_origin(self, throttle) -> None:
        """Um acerto no meio de uma varredura não limpa o rastro do IP."""
        for index in range(MAX_ATTEMPTS - 1):
            throttle.record_failure(f"conta{index}@belovale", "203.0.113.9", now=_at(index))
        throttle.record_success("conta0@belovale", "203.0.113.9")
        throttle.record_failure("mais@belovale", "203.0.113.9", now=_at(20))

        assert throttle.check("outra@belovale", "203.0.113.9", now=_at(21)) is not None

    def test_email_comparison_ignores_case(self, throttle) -> None:
        for index in range(MAX_ATTEMPTS):
            throttle.record_failure("Joao@BeloVale", "10.0.0.1", now=_at(index))

        assert throttle.check("joao@belovale", "10.0.0.1", now=_at(10)) is not None


class TestMemoryHygiene:
    def test_old_entries_do_not_accumulate_forever(self) -> None:
        throttle = InMemoryLoginThrottle()

        async def go():
            for index in range(50):
                await throttle.record_failure(
                    f"bot{index}@x", f"10.0.0.{index}", now=_at(index)
                )
            await throttle.check(
                "alguem@belovale", "10.0.0.250", now=_at(LOCKOUT_SECONDS * 10)
            )

        run(go())
        assert throttle.tracked_keys() < 50


class TestRedisKeys:
    def test_keys_expire_on_their_own(self) -> None:
        """Um bot que tenta uma vez e some não pode deixar chave eterna."""
        url = os.getenv("REDIS_URL")
        if not url:
            pytest.skip("REDIS_URL is required for Redis integration tests")
        prefix = f"bv2-test:{uuid.uuid4().hex}:"

        async def go():
            throttle = RedisLoginThrottle.from_url(url, prefix=prefix)
            try:
                await throttle.record_failure("bot@x", "198.51.100.7")
                ttls = [
                    await throttle.client.ttl(key)
                    async for key in throttle.client.scan_iter(f"{prefix}*")
                ]
            finally:
                await throttle.aclose()
            return ttls

        ttls = run(go())
        assert len(ttls) == 2
        assert all(0 < ttl <= LOCKOUT_SECONDS * 2 for ttl in ttls)


class _BrokenRedis:
    """Redis fora do ar: toda chamada falha como falharia a conexão."""

    async def check(self, *args, **kwargs):
        raise ConnectionError("redis indisponível")

    record_failure = check
    record_success = check


class TestResilience:
    def test_falls_back_to_memory_when_redis_is_down(self) -> None:
        """Redis fora do ar não pode nem trancar a fazenda para fora (falhar
        fechado) nem liberar força bruta (falhar aberto): o limite segue
        valendo no processo."""
        throttle = ResilientLoginThrottle(_BrokenRedis(), InMemoryLoginThrottle())

        async def go():
            first = await throttle.check("joao@belovale", "10.0.0.1", now=_at(0))
            for index in range(MAX_ATTEMPTS):
                await throttle.record_failure(
                    "joao@belovale", "10.0.0.1", now=_at(index)
                )
            last = await throttle.check("joao@belovale", "10.0.0.1", now=_at(9))
            return first, last

        first, last = run(go())
        assert first is None
        assert last is not None


class TestWiring:
    def test_the_app_counts_failures_in_redis_when_configured(self, monkeypatch) -> None:
        """Com REDIS_URL, a falha de login precisa chegar ao Redis — não pode
        cair na memória do processo sem ninguém perceber."""
        url = os.getenv("REDIS_URL")
        if not url or not os.getenv("POSTGRES_URL"):
            pytest.skip("REDIS_URL e POSTGRES_URL são necessários")

        from fastapi.testclient import TestClient
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        from app.core.config import get_settings
        from app.db.session import get_db_session
        from app.main import create_app

        get_settings.cache_clear()
        app = create_app()
        engine = create_async_engine(os.environ["POSTGRES_URL"], poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def override_session():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_db_session] = override_session
        email = f"ninguem-{uuid.uuid4().hex}@belovale"
        # O TestClient se apresenta sempre como a mesma origem; sem limpar,
        # execuções anteriores deixariam essa origem bloqueada.
        origin_key = "bv2:login:origin:testclient"
        account_key = f"bv2:login:account:{email}"

        async def forget():
            throttle = RedisLoginThrottle.from_url(url)
            try:
                await throttle.client.delete(origin_key, account_key)
            finally:
                await throttle.aclose()

        run(forget())
        try:
            with TestClient(app) as client:
                assert isinstance(app.state.login_throttle, ResilientLoginThrottle)
                client.post(
                    "/api/auth/login",
                    json={"email": email, "password": "errada demais"},
                )
        finally:
            get_settings.cache_clear()

        async def inspect():
            throttle = RedisLoginThrottle.from_url(url)
            try:
                return await throttle.client.zcard(account_key)
            finally:
                await throttle.aclose()

        try:
            assert run(inspect()) == 1
        finally:
            run(forget())
