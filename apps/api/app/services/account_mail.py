"""Mensagens transacionais. Tokens só seguem para o endereço confirmado."""

import smtplib
from email.message import EmailMessage
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings
from fastapi import HTTPException


class Mailer(Protocol):
    def send(self, recipient: str, subject: str, text: str) -> None: ...


class SMTPMailer:
    def send(self, recipient: str, subject: str, text: str) -> None:
        settings = get_settings()
        if not settings.smtp_host or not settings.smtp_from:
            raise HTTPException(
                503,
                "O envio de e-mail ainda não está configurado. Tente novamente mais tarde.",
            )
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = (
            settings.smtp_from,
            recipient,
            subject,
        )
        message.set_content(text)
        try:
            with smtplib.SMTP(
                settings.smtp_host, settings.smtp_port, timeout=15
            ) as smtp:
                if settings.smtp_starttls:
                    smtp.starttls()
                if settings.smtp_user:
                    smtp.login(
                        settings.smtp_user,
                        settings.smtp_password.get_secret_value()
                        if settings.smtp_password
                        else "",
                    )
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            raise HTTPException(
                503, "Não foi possível enviar o e-mail agora. Tente novamente."
            ) from error


class MemoryMailer:
    def __init__(self):
        self.messages: list[dict[str, str]] = []

    def send(self, recipient: str, subject: str, text: str) -> None:
        self.messages.append({"to": recipient, "subject": subject, "text": text})


@lru_cache
def get_mailer() -> Mailer:
    return SMTPMailer()
