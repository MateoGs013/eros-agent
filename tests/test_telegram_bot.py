"""El bot sin TELEGRAM_ALLOWED_USER_ID le dice a quien escribe cómo autorizarse (antes llamaba a un
método que no existía y el mensaje se perdía con un AttributeError en el log)."""

import unittest
from unittest.mock import AsyncMock

from eros.bot.telegram import TelegramBot


class UnauthorizedMessageTest(unittest.IsolatedAsyncioTestCase):
    async def test_sin_usuario_autorizado_explica_como_configurarlo(self):
        bot = TelegramBot()
        bot.allowed_user_id = None
        bot.send_message = AsyncMock(return_value=True)

        await bot._process_update({"message": {"from": {"id": 42}, "chat": {"id": 7}, "text": "/start"}})

        bot.send_message.assert_awaited_once()
        chat_id, text = bot.send_message.await_args.args
        self.assertEqual(chat_id, 7)
        self.assertIn("TELEGRAM_ALLOWED_USER_ID=42", text)

    async def test_otro_usuario_no_recibe_nada(self):
        bot = TelegramBot()
        bot.allowed_user_id = 1
        bot.send_message = AsyncMock(return_value=True)

        await bot._process_update({"message": {"from": {"id": 42}, "chat": {"id": 7}, "text": "/start"}})

        bot.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
