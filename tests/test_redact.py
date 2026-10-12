"""Masking before a text goes to an AI service on the internet: what is masked (and checked), what is left alone,
and that every request really goes through it. No network."""

import json
import os
import time
from types import SimpleNamespace
from unittest import mock

from desktidy import ai, cli, providers, redact
from desktidy import content as ct
from tests.helpers import IsolatedTest

IBAN = "IT60 X054 2811 1010 0000 0123 456"
TAX_CODE = "RSSMRA80A01H501U"
INVOICE = (f"ACME S.r.l. - P.IVA 01234567897\nFattura n. 2231 del 12/10/2026\nCliente: Mario Rossi, C.F. {TAX_CODE}\n"
           f"Tel. 333 123 4567 - mario.rossi@example.com\nTotale da pagare 1.220,00 entro il 30/10/2026\n"
           f"Bonifico su IBAN {IBAN}\n")


class TestChecks(IsolatedTest):
    def test_iban(self):
        for good in ("IT60X0542811101000000123456", IBAN, "DE89370400440532013000", "GB82 WEST 1234 5698 7654 32"):
            self.assertTrue(redact.iban_ok(good), good)
        for bad in ("IT61X0542811101000000123456", "IT60X05428", "1234567890123456", "ITXX X054 2811 1010"):
            self.assertFalse(redact.iban_ok(bad), bad)

    def test_luhn_and_tax_code(self):
        self.assertTrue(redact.luhn_ok("4111 1111 1111 1111"))
        self.assertFalse(redact.luhn_ok("4111 1111 1111 1112"))
        self.assertTrue(redact.luhn_ok("01234567897"))                     # a valid Italian VAT number
        self.assertTrue(redact.tax_code_ok(TAX_CODE))
        self.assertTrue(redact.tax_code_ok(TAX_CODE.lower()))
        self.assertFalse(redact.tax_code_ok("RSSMRA80A01H501A"))


class TestMask(IsolatedTest):
    def masked(self, text):
        return redact.mask(text)[0]

    def test_the_invoice(self):
        out, n = redact.mask(INVOICE)
        for secret in (IBAN, TAX_CODE, "01234567897", "333 123 4567", "mario.rossi@example.com"):
            self.assertNotIn(secret, out)
        for kept in ("Fattura n. 2231 del 12/10/2026", "1.220,00", "30/10/2026", "ACME S.r.l.", "Mario Rossi"):
            self.assertIn(kept, out)                                     # what the AI needs (names are not masked)
        self.assertEqual(n, 5)
        self.assertIn("P.IVA [VAT_NO]", out)
        self.assertIn("C.F. [TAX_CODE]", out)

    def test_a_number_followed_by_more(self):
        self.assertEqual(self.masked("carta 4111 1111 1111 1111 123"), "carta [CARD] 123")       # card and CVV
        self.assertEqual(self.masked("BE68 5390 0754 7034 BIC1"), "[IBAN] BIC1")
        self.assertEqual(self.masked("IBAN: IT60X0542811101000000123456."), "IBAN: [IBAN].")

    def test_left_alone(self):
        for text in ("Totale 1.220,00 EUR, fattura 2231 del 12/10/2026",
                     "Codice cliente 55120, POD IT001E12345678",
                     "01234567897",                                 # 11 digits without a VAT label
                     "4111 1111 1111 1112",                         # fails the Luhn check
                     "3331234567 pezzi",                            # a number without a phone label
                     "RSSMRA80A01H501A"):                           # wrong check letter
            self.assertEqual(self.masked(text), text, text)

    def test_phones(self):
        self.assertEqual(self.masked("Tel. 02 1234567"), "Tel. [PHONE]")
        self.assertEqual(self.masked("cellulare: +39 333 123 4567"), "cellulare: [PHONE]")
        self.assertEqual(self.masked("chiamare il +39 02 1234 5678 oggi"), "chiamare il [PHONE] oggi")
        self.assertEqual(self.masked("tel.\n12345\n6789"), "tel.\n12345\n6789")       # never across lines

    def test_lower_case_key_terms(self):
        self.assertEqual(self.masked("key terms: rssmra80a01h501u, it60x0542811101000000123456"),
                         "key terms: [TAX_CODE], [IBAN]")


class TestWhen(IsolatedTest):
    def test_internet_yes_this_pc_no(self):
        self.assertTrue(redact.wanted({"ai": {"provider": "groq"}}))
        self.assertTrue(redact.wanted({"ai": {"provider": "claude"}}))
        self.assertFalse(redact.wanted({"ai": {"provider": "ollama"}}))
        self.assertFalse(redact.wanted({"ai": {"provider": "groq", "redact": False}}))

    def test_a_local_service_on_another_machine_is_not_local(self):
        cfg = {"ai": {"provider": "custom", "base_url": "http://192.168.1.20:1234/v1"}}
        self.assertFalse(providers.current(cfg).local)
        self.assertTrue(redact.wanted(cfg))
        for url in ("http://localhost:1234/v1", "http://127.0.0.1:11434", "http://[::1]:8000/v1"):
            self.assertTrue(providers.current({"ai": {"provider": "custom", "base_url": url}}).local, url)

    def test_outgoing_copies_and_masks_text_only(self):
        image = {"type": "image", "source": {"data": "xyz"}}
        params = {"model": "m", "messages": [{"role": "user", "content": [{"type": "text", "text": INVOICE}, image]}]}
        said = []
        out = redact.outgoing(params, {"ai": {"provider": "groq"}}, said.append)
        self.assertNotIn(TAX_CODE, out["messages"][0]["content"][0]["text"])
        self.assertIs(out["messages"][0]["content"][1], image)
        self.assertIn(TAX_CODE, params["messages"][0]["content"][0]["text"])   # the original is untouched
        self.assertIn("5 sensitive value(s) masked", said[0])
        self.assertIs(redact.outgoing(params, {"ai": {"provider": "ollama"}}), params)


class TestEveryRequest(IsolatedTest):
    """complete() (all OpenAI-compatible services and Claude) and submit() (Claude batches) mask what they send."""

    def setUp(self):
        super().setUp()
        self.params = {"model": "m", "max_tokens": 10, "system": "s",
                       "messages": [{"role": "user", "content": [{"type": "text", "text": INVOICE}]}]}

    def test_openai_compatible(self):
        cfg = self.config(ai={"mode": "all", "provider": "groq"})
        with mock.patch.object(ai, "_complete_openai", return_value="{}") as sent:
            ai.complete(self.params, cfg, "key", lambda m: None, files=1)
        self.assertNotIn(TAX_CODE, json.dumps(sent.call_args[0][0]))

    def test_claude_now_and_in_batches(self):
        cfg = self.config(ai={"mode": "all", "provider": "claude"})
        client = mock.MagicMock()
        client.messages.create.return_value = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=1, output_tokens=1, cache_creation_input_tokens=0,
                                  cache_read_input_tokens=0), stop_reason="end_turn", content=[])
        client.messages.batches.create.return_value = SimpleNamespace(id="b1")
        with mock.patch.object(ai, "_claude_client", return_value=client), \
                mock.patch.object(ai, "_book", return_value=0.0), mock.patch.object(ai, "_text_of", return_value="{}"):
            ai.complete(self.params, cfg, "key", lambda m: None, files=1)
            p = self.write("scan0001.txt", INVOICE)
            an = ct.analyze(p, False)
            item = ai.Item(p, False, os.path.dirname(p), 1, time.time(), analysis=an, private=True)
            ai.submit([item], cfg, "key", lambda m: None)
        self.assertNotIn(TAX_CODE, json.dumps(client.messages.create.call_args.kwargs, default=str))
        batch = json.dumps(client.messages.batches.create.call_args.kwargs, default=str)
        self.assertNotIn(TAX_CODE, batch)
        self.assertNotIn("0123 456", batch)

    def test_a_private_picture_is_not_sent_when_masking(self):
        cfg = self.config(ai={"mode": "all", "provider": "openai"})        # a service that reads images
        p = self.write("scan0001.txt", "x")
        visions = []
        with mock.patch.object(ai, "_payload", side_effect=lambda item, vision=True: visions.append(vision) or ("", None)):
            ai.build([ai.Item(p, False, "", 1, 0.0, private=True), ai.Item(p, False, "", 1, 0.0)], cfg)
        self.assertEqual(visions, [False, True])

    def test_always_ai_says_what_is_masked(self):
        cfg = self.config(ai={"mode": "limited", "provider": "groq"})
        said = []
        with mock.patch.object(cli.ai_cmds, "warn"), mock.patch.object(cli.ai_cmds, "hint", side_effect=said.append), \
                mock.patch.object(cli.ai_cmds, "confirm", return_value=True) as asked, mock.patch.object(cli.ui, "INTERACTIVE", True):
            self.assertTrue(cli.confirm_everything(cfg))
        asked.assert_called_once()
        self.assertTrue(any("masked" in s and "addresses are not" in s for s in said))
