"""Sending email with Python's standard library (smtplib), set up by SMTP_HOST, SMTP_PORT,
SMTP_USER, SMTP_PASSWORD and SMTP_FROM in .env. Without SMTP_HOST nothing is sent: the
message is printed in the backend's log instead, so the sign-up works on your own computer.
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from app import config

log = logging.getLogger("uvicorn.error")


class MailError(Exception):
    """The email could not be sent."""


def send(to: str, subject: str, text: str) -> None:
    if not config.SMTP_HOST:
        log.warning("Email (no SMTP_HOST set, so it is only printed here) to %s: %s\n%s", to, subject, text)
        return
    message = EmailMessage()
    message["From"] = config.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    try:
        if config.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=20, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
        with server:
            server.ehlo()  # the server lists what it offers (STARTTLS, AUTH) only after the greeting
            if config.SMTP_PORT != 465 and server.has_extn("starttls"):
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if config.SMTP_USER:
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        log.warning("Email to %s not sent: %s", to, type(error).__name__)
        raise MailError("The email could not be sent. Please try again in a moment.") from error
