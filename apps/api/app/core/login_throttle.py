"""Limite de tentativas de login.

Exposta na internet pública, a tela de login é varrida por bots que testam
senhas em sequência. Sem limite, a senha de um funcionário é adivinhável por
repetição — e nenhuma política de senha compensa tentativas ilimitadas.

O limite é aplicado por **conta** e por **origem**, porque cada um sozinho tem
um furo: limitar só por conta permite varrer muitas contas de um mesmo IP, e
limitar só por origem pune a fazenda inteira quando todos saem pelo mesmo
endereço.

O estado é mantido em memória do processo. Isso é suficiente enquanto a API
roda em um processo só; com mais de uma réplica, cada uma contaria em
separado. O lugar natural para isso depois é o Redis que já existe no projeto
— anotado como limitação conhecida, não como descuido.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

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


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LoginThrottle:
    """Contador de falhas por conta e por origem.

    Não distingue "conta inexistente" de "senha errada": responder de forma
    diferente revelaria quais e-mails existem no sistema.
    """

    def __init__(self) -> None:
        self._failures: dict[str, list[datetime]] = defaultdict(list)

    @staticmethod
    def _account_key(email: str) -> str:
        return f"account:{email.strip().lower()}"

    @staticmethod
    def _origin_key(origin: str) -> str:
        return f"origin:{origin}"

    def _prune(self, key: str, now: datetime) -> list[datetime]:
        cutoff = now - timedelta(seconds=WINDOW_SECONDS)
        kept = [moment for moment in self._failures[key] if moment > cutoff]
        if kept:
            self._failures[key] = kept
        else:
            self._failures.pop(key, None)
        return kept

    def _retry_after(self, key: str, now: datetime) -> int | None:
        attempts = self._prune(key, now)
        if len(attempts) < MAX_ATTEMPTS:
            return None
        unlock_at = attempts[-1] + timedelta(seconds=LOCKOUT_SECONDS)
        remaining = (unlock_at - now).total_seconds()
        return math.ceil(remaining) if remaining > 0 else None

    def check(
        self, email: str, origin: str, *, now: datetime | None = None
    ) -> int | None:
        """Segundos até poder tentar de novo, ou ``None`` se estiver liberado."""
        moment = now or _now()
        if len(self._failures) > _PURGE_THRESHOLD:
            self.purge_expired(now=moment)
        waits = [
            self._retry_after(self._account_key(email), moment),
            self._retry_after(self._origin_key(origin), moment),
        ]
        blocking = [wait for wait in waits if wait is not None]
        return max(blocking) if blocking else None

    def record_failure(
        self, email: str, origin: str, *, now: datetime | None = None
    ) -> None:
        moment = now or _now()
        self._failures[self._account_key(email)].append(moment)
        self._failures[self._origin_key(origin)].append(moment)

    def record_success(self, email: str, origin: str) -> None:
        """Login bem-sucedido zera a conta; a origem continua contando, para
        que um acerto no meio de uma varredura não limpe o rastro."""
        self._failures.pop(self._account_key(email), None)

    def tracked_keys(self) -> int:
        """Quantas chaves estão em memória. Existe para o teste de higiene."""
        return len(self._failures)

    def purge_expired(self, *, now: datetime | None = None) -> None:
        moment = now or _now()
        for key in list(self._failures):
            self._prune(key, moment)


#: Instância do processo. Injetada como dependência para que testes usem a sua.
_throttle = LoginThrottle()


def get_login_throttle() -> LoginThrottle:
    return _throttle
