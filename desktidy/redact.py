# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""Sensitive numbers masked before a text leaves this computer for an AI service on the internet.

  IT60 X054 2811 1010 0000 0123 456   ->  [IBAN]        (only if it passes the IBAN check, mod 97)
  4111 1111 1111 1111                 ->  [CARD]        (13-19 digits passing the Luhn check)
  RSSMRA80A01H501U                    ->  [TAX_CODE]    (Italian codice fiscale with a valid check letter)
  P.IVA 01234567897                   ->  [VAT_NO]      (11 digits after a VAT label, valid check digit)
  mario.rossi@example.com             ->  [EMAIL]
  tel. 333 123 4567, +39 02 1234567   ->  [PHONE]       (after a phone label, or written with +/00)

The AI still understands what the document is ("invoice 2231 from Acme, 1,220 euro, due 30 October"); the
numbers that identify you stay here. Checked, not guessed: a number is masked only when its check digits say it
is one, so amounts, dates and invoice numbers are left alone. Names and street addresses are NOT masked: they
can't be told apart from the rest of the text reliably.

When: for every request to a service that is not on this computer (ai.redact, on by default); Ollama and other
servers on this PC get the text as it is. ai.complete() and ai.submit() call outgoing(): no request skips it.
"""

from __future__ import annotations

import re

LABELS = {"IBAN": "[IBAN]", "CARD": "[CARD]", "TAX_CODE": "[TAX_CODE]", "VAT_NO": "[VAT_NO]", "EMAIL": "[EMAIL]",
          "PHONE": "[PHONE]"}

IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b", re.I)
CARD = re.compile(r"(?<![\d.,])\d(?:[ -]?\d){12,18}(?![\d.,]\d)")
TAX_CODE = re.compile(r"\b[A-Z]{6}[0-9LMNPQRSTUV]{2}[ABCDEHLMPRST][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]\b",
                      re.I)
VAT_NO = re.compile(r"(?P<label>\b(?:p\.?\s?iva|partita\s+iva|c\.?\s?f\.?\s?/\s?p\.?\s?iva|codice\s+fiscale|c\.f\.|"
                    r"vat(?:\s+(?:no|number|reg(?:istration)?(?:\s+no)?))?\.?)\s*[:.]?\s*(?:IT\s?)?)(?P<n>\d{11})\b",
                    re.I)
EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_LABELLED = re.compile(r"(?P<label>\b(?:tel(?:efono)?|phone|cell(?:ulare)?|mobile|fax|whatsapp|mob)\b\.?\s*[:.]?\s*)"
                            r"(?P<n>(?:\+|00)?\d(?:[ ./-]?\d){5,14})(?!\d)", re.I)
PHONE_INTERNATIONAL = re.compile(r"(?<![\w+])(?:\+|00)[1-9]\d{0,2}(?:[ ./-]?\d){6,12}(?!\d)")

_ODD = dict(zip("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12,
                 14, 16, 10, 22, 25, 24, 23]))
_EVEN = {**{str(d): d for d in range(10)}, **{chr(65 + i): i for i in range(26)}}


def iban_ok(text: str) -> bool:
    s = re.sub(r"\s", "", text).upper()
    if not 15 <= len(s) <= 34 or not s[:2].isalpha() or not s[2:4].isdigit():
        return False
    moved = s[4:] + s[:4]
    try:
        return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1
    except ValueError:
        return False


def luhn_ok(digits: str) -> bool:
    d = [int(c) for c in digits if c.isdigit()]
    if not d:
        return False
    total = 0
    for i, n in enumerate(reversed(d)):
        if i % 2:
            n *= 2
            n -= 9 if n > 9 else 0
        total += n
    return total % 10 == 0


def tax_code_ok(code: str) -> bool:
    """The check letter of an Italian codice fiscale (the 16th character)."""
    c = code.upper()
    if len(c) != 16:
        return False
    total = sum(_ODD[ch] if i % 2 == 0 else _EVEN[ch] for i, ch in enumerate(c[:15]))
    return chr(65 + total % 26) == c[15]


def card_ok(text: str) -> bool:
    return 13 <= sum(c.isdigit() for c in text) <= 19 and luhn_ok(text)


def _valid_prefix(text: str, ok) -> int:
    """Length of the longest prefix of `text` that passes `ok` (0 if none): "4111 1111 1111 1111 123" (a card and
    its CVV) or an IBAN followed by "BIC1" are found although the whole match is not a valid number."""
    for end in range(len(text), 0, -1):
        if text[end - 1].isalnum() and ok(text[:end]):
            return end
    return 0


def mask(text: str) -> tuple[str, int]:
    """(the text with the sensitive numbers replaced, how many were replaced)."""
    count = 0

    def sub(rx: re.Pattern, label: str, check=None, group: str | None = None, prefix: bool = False):
        nonlocal text, count

        def repl(m: re.Match) -> str:
            nonlocal count
            value = m.group(group) if group else m.group(0)
            if check:
                end = _valid_prefix(value, check) if prefix else (len(value) if check(value) else 0)
                if not end:
                    return m.group(0)
            else:
                end = len(value)
            count += 1
            return (m.group("label") if group else "") + LABELS[label] + value[end:]
        text = rx.sub(repl, text)

    sub(EMAIL, "EMAIL")
    sub(IBAN, "IBAN", iban_ok, prefix=True)
    sub(TAX_CODE, "TAX_CODE", tax_code_ok)
    sub(VAT_NO, "VAT_NO", luhn_ok, group="n")
    sub(CARD, "CARD", card_ok, prefix=True)
    sub(PHONE_LABELLED, "PHONE", group="n")
    sub(PHONE_INTERNATIONAL, "PHONE")
    return text, count


def wanted(cfg: dict) -> bool:
    """Mask for this request? Yes for a service on the internet (unless ai.redact is false), never for one on
    this computer."""
    from . import providers
    return cfg.get("ai", {}).get("redact", True) is not False and not providers.current(cfg).local


def outgoing(params: dict, cfg: dict, log=None) -> dict:
    """The request with every text block masked (a copy: the original is untouched). Images can't be masked:
    the requests that would carry a private one leave it out when masking is on (ai.build)."""
    if not wanted(cfg):
        return params
    total = 0
    messages = []
    for message in params.get("messages", []):
        content = message.get("content")
        if isinstance(content, str):
            content, n = mask(content)
            total += n
        elif isinstance(content, list):
            blocks = []
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    masked, n = mask(b.get("text", ""))
                    total += n
                    b = {**b, "text": masked}
                blocks.append(b)
            content = blocks
        messages.append({**message, "content": content})
    if total and log:
        log(f"AI: {total} sensitive value(s) masked before sending (IBAN, tax codes, e-mails, phones...)")
    return {**params, "messages": messages}
