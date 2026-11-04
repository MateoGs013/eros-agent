"""Tests del cliente de IA con textos largos: timeout por llamada y respuesta cortada por largo.

Ninguno sale a la red: el cliente HTTP está simulado.
"""

import unittest
from unittest.mock import MagicMock, patch

from eros.config import Settings
from eros.integrations.llm import LLMClient, LLMOutputError


class FakeAsyncClient:
    """Reemplaza httpx.AsyncClient: guarda el timeout y responde lo que se le indique."""

    instances: list["FakeAsyncClient"] = []
    body: dict = {}

    def __init__(self, timeout=None, **kw):
        self.timeout = timeout
        self.calls = 0
        FakeAsyncClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls += 1
        resp = MagicMock(status_code=200, text="ok")
        resp.json.return_value = FakeAsyncClient.body
        return resp


def gemini_body(text: str, finish: str = "STOP") -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}]}


class TestLongOutputs(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        LLMClient._quota_exhausted_until = 0.0
        FakeAsyncClient.instances = []
        self.llm = LLMClient()
        self.llm.settings = Settings(
            gemini_api_key="test-key",
            gemini_model="gemini-a",
            gemini_fallback_models=["gemini-b", "gemini-c"],
        )

    async def test_timeout_default_and_per_call(self):
        FakeAsyncClient.body = gemini_body('{"ok": true}')
        with patch("eros.integrations.llm.httpx.AsyncClient", FakeAsyncClient):
            self.assertEqual(await self.llm.generate("hola"), '{"ok": true}')
            await self.llm.generate("hola", timeout=150.0, max_tokens=8192)
        self.assertEqual(FakeAsyncClient.instances[0].timeout, 45.0)
        self.assertEqual(FakeAsyncClient.instances[1].timeout, 150.0)

    async def test_max_tokens_raises_and_does_not_cascade(self):
        FakeAsyncClient.body = gemini_body('{"markdown": "texto cort', finish="MAX_TOKENS")
        with patch("eros.integrations.llm.httpx.AsyncClient", FakeAsyncClient):
            with self.assertRaises(LLMOutputError) as ctx:
                await self.llm.generate("artículo largo", json_mode=True, max_tokens=8192)
        self.assertIn("se cortó por largo", str(ctx.exception))
        self.assertEqual(len(FakeAsyncClient.instances), 1, "no prueba el resto de la cascada")


if __name__ == "__main__":
    unittest.main()
