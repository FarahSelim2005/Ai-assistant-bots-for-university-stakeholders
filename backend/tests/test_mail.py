"""Tests for app/mail.py: the email is sent over STARTTLS with a login (a stand-in SMTP server
that behaves like Gmail: STARTTLS and AUTH are only known after the greeting), or only logged
without SMTP_HOST. Nothing is sent.

Run from the backend folder:
    python -m unittest discover -s tests -v
"""
import unittest
from unittest import mock

from app import config, mail


class FakeSmtp:
    """Like smtplib.SMTP against Gmail: extensions are known only after ehlo(); login needs TLS."""
    sent = []

    def __init__(self, host, port, timeout=None):
        self.greeted = self.tls = False
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        self.greeted = True
        self.calls.append("ehlo")

    def has_extn(self, name):
        return self.greeted and name == "starttls"

    def starttls(self, context=None):
        self.tls = True
        self.calls.append("starttls")

    def login(self, user, password):
        if not self.tls:
            raise mail.smtplib.SMTPNotSupportedError("SMTP AUTH extension not supported by server.")
        self.calls.append("login")

    def send_message(self, message):
        FakeSmtp.sent.append((message["To"], message["Subject"], self.calls))


class Sending(unittest.TestCase):
    def test_starttls_then_login_then_send(self):
        FakeSmtp.sent = []
        with mock.patch.multiple(config, SMTP_HOST="smtp.example.com", SMTP_PORT=587, SMTP_USER="me@example.com",
                                 SMTP_PASSWORD="app-password", SMTP_FROM="UniBots <me@example.com>"), \
             mock.patch.object(mail.smtplib, "SMTP", FakeSmtp):
            mail.send("a@uni.example", "Your sign-up code: 123456", "Your code is 123456")
        self.assertEqual(FakeSmtp.sent, [("a@uni.example", "Your sign-up code: 123456", ["ehlo", "starttls", "ehlo", "login"])])

    def test_no_host_only_logs(self):
        with mock.patch.object(config, "SMTP_HOST", ""), mock.patch.object(mail.smtplib, "SMTP", side_effect=AssertionError("no SMTP")):
            with self.assertLogs("uvicorn.error", "WARNING") as logged:
                mail.send("a@uni.example", "Your sign-up code: 123456", "Your code is 123456")
        self.assertIn("123456", logged.output[0])


if __name__ == "__main__":
    unittest.main()
