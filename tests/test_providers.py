# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""Other AI services: presets, request conversion, the fallback ladder and a full answer, against a fake
OpenAI-compatible server running on localhost (no real service is contacted)."""

import json
import os
import re
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from desktidy import ai, classifier, naming, providers, usage
from desktidy import content as ct
from tests.helpers import IsolatedTest


class FakeServer(BaseHTTPRequestHandler):
    """Answers /models and /chat/completions; can refuse json_schema to exercise the fallback ladder."""
    refuse_schema = False
    requests: list = []
    folder_index = 1
    pick_recipes = False      # answer with the number the request gave to the Recipes folder

    def log_message(self, *args):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.headers.get("Authorization") == "Bearer bad":
            return self._send(401, {"error": {"message": "invalid key"}})
        self._send(200, {"data": [{"id": "gemma3:4b"}, {"id": "test-model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeServer.requests.append(body)
        if FakeServer.refuse_schema and body.get("response_format", {}).get("type") == "json_schema":
            return self._send(400, {"error": {"message": "response_format json_schema not supported"}})
        if "organising personal files" in body["messages"][0]["content"]:
            answer = {"tips": [{"k": "pin", "t": "Pin the recipes folder", "d": "Recipes keep arriving.", "f": [2, 99]}]}
            return self._send(200, {"choices": [{"message": {"content": json.dumps(answer)}}],
                                    "usage": {"prompt_tokens": 900, "completion_tokens": 60}})
        user_text = "".join(p.get("text", "") for p in body["messages"][1]["content"])
        found = re.search(r"^(\d+)\s+Recipes$", user_text, re.M) if FakeServer.pick_recipes else None
        folder = int(found.group(1)) if found else FakeServer.folder_index
        answer = {"files": [{"n": 1, "f": folder, "c": "h", "name": "Grocery list", "why": "food"}]}
        self._send(200, {"choices": [{"message": {"content": "```json\n" + json.dumps(answer) + "\n```"}}],
                         "usage": {"prompt_tokens": 321, "completion_tokens": 45}})


class TestPresets(unittest.TestCase):
    def test_every_preset_is_complete(self):
        for pid, p in providers.PROVIDERS.items():
            self.assertEqual(pid, p.id)
            self.assertIn(p.kind, ("anthropic", "openai"))
            if p.kind == "openai":
                self.assertTrue(p.base_url.startswith("http"), pid)
        self.assertTrue(providers.PROVIDERS["groq"].free and providers.PROVIDERS["ollama"].free)
        self.assertFalse(providers.PROVIDERS["claude"].free)

    def test_free_plans_cost_nothing_and_overrides_win(self):
        self.assertEqual(providers.prices({"ai": {"provider": "groq"}}), (0.0, 0.0))
        self.assertEqual(providers.prices({"ai": {"provider": "claude"}}), (1.0, 5.0))
        self.assertEqual(providers.prices({"ai": {"provider": "openai", "model": "gpt-5-nano"}}), (0.05, 0.40))
        self.assertIsNone(providers.prices({"ai": {"provider": "openai", "model": "some-new-model"}}))
        self.assertEqual(providers.prices({"ai": {"provider": "custom", "price_per_million": [1, 2]}}), (1.0, 2.0))

    def test_model_and_base_url(self):
        self.assertEqual(providers.model({"ai": {"provider": "claude", "model": "sonnet"}}), "claude-sonnet-5-5")
        self.assertEqual(providers.model({"ai": {"provider": "groq"}}), "openai/gpt-oss-20b")
        p = providers.current({"ai": {"provider": "custom", "base_url": "http://x:1/v1/", "vision": True}})
        self.assertEqual((p.base_url, p.vision), ("http://x:1/v1", True))
        self.assertEqual(providers.current({"ai": {"provider": "nope"}}).id, "claude")


class TestConversion(unittest.TestCase):
    params = {"model": "m", "max_tokens": 100, "system": "S", "messages": [{"role": "user", "content": [
        {"type": "text", "text": "Folders"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}},
        {"type": "text", "text": "#1"}]}]}

    def test_vision_service_gets_a_data_url(self):
        body = ai.to_openai(self.params, providers.PROVIDERS["gemini"])
        parts = body["messages"][1]["content"]
        self.assertEqual(parts[1]["image_url"]["url"], "data:image/jpeg;base64,QUJD")
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertIn("JSON", body["messages"][0]["content"])

    def test_text_only_service_never_gets_images(self):
        body = ai.to_openai(self.params, providers.PROVIDERS["groq"])
        self.assertEqual([p["type"] for p in body["messages"][1]["content"]], ["text", "text"])
        self.assertEqual(body["reasoning_effort"], "low")

    def test_ladder_levels(self):
        p = providers.PROVIDERS["openai"]
        self.assertIn("max_completion_tokens", ai.to_openai(self.params, p))
        self.assertEqual(ai.to_openai(self.params, p, 1)["response_format"], {"type": "json_object"})
        self.assertNotIn("reasoning_effort", ai.to_openai(self.params, p, 1))
        self.assertNotIn("response_format", ai.to_openai(self.params, p, 2))

    def test_answer_inside_code_fences(self):
        text = 'Sure!\n```json\n{"files":[{"n":1,"f":1,"c":"m","name":"","why":"x"}]}\n```'
        self.assertEqual(ai.parse(text, 1, ["inbox", "A"])[1].folder, "A")


class TestFakeServer(IsolatedTest):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeServer)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        super().setUp()
        FakeServer.requests, FakeServer.refuse_schema, FakeServer.pick_recipes = [], False, False
        ai._ladder.clear()
        self.cfg = self.config(ai={"mode": "limited", "provider": "custom", "base_url": self.url, "model": "test-model",
                                   "candidate_folders": [{"path": "{D}", "depth": 2}]})
        self.folder("dest", "Recipes")

    def item(self):
        p = self.write("scan0002.txt", "milk eggs bread butter cheese apples bananas pasta rice tomatoes " * 4)
        an = ct.analyze(p, False, self.cfg)
        return ai.item_for(p, False, os.path.dirname(p), an, classifier.decide(p, False, self.cfg, an),
                           naming.plan(an, self.cfg), self.cfg)

    def ask(self, item):
        _, folder_list = ai.build([item], self.cfg)
        FakeServer.folder_index = len(folder_list) - 1
        self.expected = folder_list[-1]
        return ai.ask([item], self.cfg, "test-key", lambda m: None)

    def test_full_answer_and_free_spend(self):
        answers = self.ask(self.item())
        self.assertEqual(answers[1].folder, self.expected)
        self.assertEqual(answers[1].name, "Grocery_list")
        u = usage.read()
        self.assertEqual((u["total_files"], u["total_usd"]), (1, 0.0))
        self.assertEqual(u["models"]["test-model"]["input_tokens"], 321)

    def test_service_that_refuses_json_schema(self):
        FakeServer.refuse_schema = True
        self.assertEqual(self.ask(self.item())[1].folder, self.expected)
        self.assertEqual([r.get("response_format", {}).get("type") for r in FakeServer.requests],
                         ["json_schema", "json_object"])
        FakeServer.requests.clear()
        self.ask(self.item())                       # the working shape is remembered
        self.assertEqual(len(FakeServer.requests), 1)

    def test_key_check(self):
        self.assertTrue(ai.check_key("good", self.cfg)[0])
        cloud = providers.Provider("x", "X", "openai", "m", self.url, "X_KEY")
        self.assertFalse(ai.check_key("bad", provider=cloud)[0])

    def test_unreachable_server_falls_back(self):
        cfg = self.config(ai={"mode": "limited", "provider": "custom", "base_url": "http://127.0.0.1:9/v1",
                              "candidate_folders": [{"path": "{D}", "depth": 2}]})
        said = []
        params_item = self.item()
        self.assertIsNone(ai.ask([params_item], cfg, "k", said.append))
        self.assertTrue(any("cannot reach" in s for s in said))
        ai._paused_until[0] = 0.0

    def test_a_full_pass_of_the_service(self):
        """Nothing mocked between the service and the AI service: what really runs at every pass."""
        from desktidy import folders, service
        cfg = self.config(ai={"mode": "limited", "provider": "custom", "base_url": self.url, "model": "test-model",
                              "gather_seconds": 0, "candidate_folders": [{"path": "{D}", "depth": 2}]})
        folders.pin(self.dest("Recipes"))           # pinned folders are always in the short list
        FakeServer.pick_recipes = True
        self.write("scan0002.txt", "milk eggs bread butter cheese apples bananas pasta rice tomatoes " * 4)
        service.Service(service.Options()).tick(cfg)
        self.assertEqual(os.listdir(self.dest("Recipes")), ["Grocery_list.txt"])
        self.assertIn("name suggested by AI", service.read_moves()[0]["reason"])

    def test_organisation_advice(self):
        from desktidy import advice
        said = []
        result = advice.generate(self.cfg, said.append)
        self.assertEqual(result["tips"][0]["kind"], "pin")
        ov = advice.overview(self.cfg)
        self.assertEqual(result["tips"][0]["paths"], [ov.folders[1]])     # 99 does not exist: dropped
        self.assertEqual(advice.load()["tips"], result["tips"])
        u = usage.read()
        self.assertEqual((u["total_files"], u["days"][max(u["days"])]["requests"]), (0, 1))  # no file counted
        self.assertIn("folder organisation", said[0])
        sent = FakeServer.requests[-1]["messages"][1]["content"][0]["text"]
        self.assertIn("Recipes", sent)


if __name__ == "__main__":
    unittest.main()
