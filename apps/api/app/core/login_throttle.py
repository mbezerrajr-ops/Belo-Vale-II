"""Limite de tentativas de login.

Exposta na internet pública, a tela de login é varrida por bots que testam
senhas em sequência. Sem limite, a senha de um funcionário é adivinhável por
repetição — e nenhuma política de senha compensa tentativas ilimitadas.

O limite é aplicado por **conta** e por **origem**, porque cada um sozinho tem
um furo: limitar só por conta permite varrer muitas contas de um mesmo IP, e
limitar só por origem pune a fazenda inteira quando todos saem pelo mesmo
endereço.

Duas implementações com as mesmas regras:

- ``RedisLoginThrottle``: o contador vive no Redis, compartilhado entre
  réplicas da API e preservado quando ela reinicia. É a de produção.
- ``InMemoryLoginThrottle``: o contador vive no processo. Serve a quem roda
  sem Redis e é a reserva quando o Redis cai.

``ResilientLoginThrottle`` junta as duas. Com o Redis fora do ar, falhar
fechado trancaria a fazenda inteira do lado de fora, e falhar aberto liberaria
força bruta; a reserva em memória mantém o limite valendo no processo até o
Redis voltar.
"""

from __future__ import annotations

import logging
import math
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Protocol

from fastapi import Request
from redis.asyncio import Redis
from redis.exceptions import RedisError


logger = logging.getLogger(__name__)

#: Tentativas falhas antes do bloqueio. Folgado o bastante para quem errou a
#: senha no celular, apertado o bastante para inviabilizar varredura.
MAX_ATTEMPTS = 5

#: Duração do bloqueio.
LOCKOUT_SECONDS = 15 * 60

#: Janela em que as falhas são contadas. Falhas mais antigas que isso não
#: somam, para que erros espaçados ao longo de um dia não bloqueiem ninguém.
WINDOW_SECONDS = 15 * 60

#: A partir de quantas chaves em memória vale varrer as expiradas. Sem isso,
#: uma varredura de bots deixaria uma entrada por conta e por IP tentado,
#: crescendo sem limite.
_PURGE_THRESHOLD = 32

#: Tempo máximo esperando o Redis. O login não pode travar porque o Redis
#: está lento; passado isso, vale a reserva em memória.
_REDIS_TIMEOUT_SECONDS = 0.5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _account_key(email: str) -> str:
    return f"account:{email.strip().lower()}"


def _origin_key(origin: str) -> str:
    return f"origin:{origin}"


class LoginThrottle(Protocol):
    """Contador de falhas por conta e por origem.

    Não distingue "conta inexistente" de "senha errada": responder de forma
    diferente revelaria quais e-mails existem no sistema.
    """

    async def check(
        self, email: str, origin: str, *, now: datetime | None = None
    ) -> int | None:
        """Segundos até poder tentar de novo, ou ``None`` se estiver liberado."""

    async def record_failure(
        self, email: str, origin: str, *, now: datetime | None = None
    ) -> None: ...

    async def record_success(self, email: str, origin: str) -> None:
        """Login bem-sucedido zera a conta; a origem continua contando, para
        que um acerto no meio de uma varredura não limpe o rastro."""


def _retry_after(attempts: int, last: datetime | None, now: datetime) -> int | None:
    if attempts < MAX_ATTEMPTS or last is None:
        return None
    remaining = (last + timedelta(seconds=LOCKOUT_SECONDS) - now).total_seconds()
    return math.ceil(remaining) if remaining > 0 else None


def _worst(waits: list[int | None]) -> int | None:
    blocking = [wait for wait in waits if wait is not None]
    return max(blocking) if blocking else None


class InMemoryLoginThrottle:
    """Contador no processo. Ver o docstring do módulo."""

    def __init__(self) -> None:
        self._failures: dict[str, list[datetime]] = defaultdict(list)

    def _prune(self, key: str, now: datetime) -> list[datetime]:
        cutoff = now - timedelta(seconds=WINDOW_SECONDS)
        kept = [moment for moment in self._failures[key] if moment > cutoff]
        if kept:
            self._failures[key] = kept
        else:
            self._failures.pop(key, None)
        return kept

    def _wait(self, key: str, now: datetime) -> int | None:
        attempts = self._prune(key, now)
        return _retry_after(len(attempts), attempts[-1] if attempts else None, now)

    async def check(
        self, email: str, origin: str, *, now: datetime | None = None
    ) -> int | None:
        moment = now or _now()
        if len(self._failures) > _PURGE_THRESHOLD:
            self.purge_expired(now=moment)
        return _worst(
            [
                self._wait(_account_key(email), moment),
                self._wait(_origin_key(origin), moment),
            ]
        )

    async def record_failure(
        self, email: str, origin: str, *, now: datetime | None = None
    ) -> None:
        moment = now or _now()
        self._failures[_account_key(email)].append(moment)
        self._failures[_origin_key(origin)].append(moment)

    async def record_success(self, email: str, origin: str) -> None:
        self._failures.pop(_account_key(email), None)

    def tracked_keys(self) -> int:
        """Quantas chaves estão em memória. Existe para o teste de higiene."""
        return len(self._failures)

    def purge_expired(self, *, now: datetime | None = None) -> None:
        moment = now or _now()
        for key in list(self._failures):
            self._prune(key, moment)


class RedisLoginThrottle:
    """Contador no Redis.

    Cada chave é um *sorted set*: um membro por falha, com o horário como
    score. Contar a janela é remover o que ficou para trás e medir o tamanho.
    Toda chave expira sozinha, então um bot que tenta uma vez e some não
    deixa lixo.
    """

    def __init__(self, client: Redis, *, prefix: str = "bv2:login:") -> None:
        self.client = client
        self._prefix = prefix

    @classmethod
    def from_url(cls, url: str, *, prefix: str = "bv2:login:") -> RedisLoginThrottle:
        client = Redis.from_url(
            url,
            socket_timeout=_REDIS_TIMEOUT_SECONDS,
            socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
        )
        return cls(client, prefix=prefix)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _wait(self, key: str, now: datetime) -> int | None:
        full = self._prefix + key
        cutoff = (now - timedelta(seconds=WINDOW_SECONDS)).timestamp()
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(full, "-inf", cutoff)
            pipe.zcard(full)
            pipe.zrange(full, -1, -1, withscores=True)
            _, attempts, last = await pipe.execute()
        last_at = (
            datetime.fromtimestamp(last[0][1], tz=timezone.utc) if last else None
        )
        return _retry_after(attempts, last_at, now)

    async def check(
        self, email: str, origin: str, *, now: datetime | None = None
    ) -> int | None:
        moment = now or _now()
        return _worst(
            [
                await self._wait(_account_key(email), moment),
                await self._wait(_origin_key(origin), moment),
            ]
        )

    async def record_failure(
        self, email: str, origin: str, *, now: datetime | None = None
    ) -> None:
        moment = (now or _now()).timestamp()
        # Membro único: duas falhas no mesmo instante contam como duas.
        member = f"{moment}:{uuid.uuid4().hex}"
        ttl = WINDOW_SECONDS + LOCKOUT_SECONDS
        async with self.client.pipeline(transaction=True) as pipe:
            for key in (_account_key(email), _origin_key(origin)):
                pipe.zadd(self._prefix + key, {member: moment})
                pipe.expire(self._prefix + key, ttl)
            await pipe.execute()

    async def record_success(self, email: str, origin: str) -> None:
        await self.client.delete(self._prefix + _account_key(email))


class ResilientLoginThrottle:
    """Redis quando disponível; memória do processo quando não."""

    def __init__(self, primary: LoginThrottle, fallback: InMemoryLoginThrottle) -> None:
        self._primary = primary
        self._fallback = fallback

    @staticmethod
    def _warn(error: Exception) -> None:
        # Sem o e-mail no log: o registro de indisponibilidade não precisa
        # dizer quem estava tentando entrar.
        logger.warning(
            "login throttle: Redis indisponível, usando memória do processo (%s)",
            type(error).__name__,
        )

    async def check(self, email, origin, *, now=None):
        try:
            return await self._primary.check(email, origin, now=now)
        except (RedisError, OSError) as error:
            self._warn(error)
            return await self._fallback.check(email, origin, now=now)

    async def record_failure(self, email, origin, *, now=None):
        # A reserva sempre recebe a falha: se o Redis cair logo depois, o
        # processo já conhece as tentativas recentes em vez de recomeçar do
        # zero.
        await self._fallback.record_failure(email, origin, now=now)
        try:
            await self._primary.record_failure(email, origin, now=now)
        except (RedisError, OSError) as error:
            self._warn(error)

    async def record_success(self, email, origin):
        await self._fallback.record_success(email, origin)
        try:
            await self._primary.record_success(email, origin)
        except (RedisError, OSError) as error:
            self._warn(error)


def build_login_throttle(redis_url: str | None) -> LoginThrottle:
    """Limitador para a configuração dada.

    Sem ``REDIS_URL`` o limite fica só em memória — aceitável num processo
    único de desenvolvimento. Em produção o validador de configuração já
    exige ``REDIS_URL``.
    """
    memory = InMemoryLoginThrottle()
    if not redis_url:
        return memory
    return ResilientLoginThrottle(RedisLoginThrottle.from_url(redis_url), memory)


async def close_login_throttle(throttle: LoginThrottle) -> None:
    primary = getattr(throttle, "_primary", None)
    if isinstance(primary, RedisLoginThrottle):
        await primary.aclose()


def get_login_throttle(request: Request) -> LoginThrottle:
    """O limitador da aplicação, criado no ciclo de vida dela.

    Criado ali, e não num cache de módulo, porque o cliente Redis assíncrono
    fica preso ao event loop que o abriu. Uma aplicação montada sem o ciclo
    de vida (alguns testes) recebe um limitador em memória próprio.
    """
    state = request.app.state
    if not hasattr(state, "login_throttle"):
        state.login_throttle = InMemoryLoginThrottle()
    return state.login_throttle
