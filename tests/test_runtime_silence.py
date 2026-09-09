"""Runtime checks of the three production bugs, without calling Claude."""

import unittest
from unittest.mock import AsyncMock, patch


def _state(**overrides):
    base = {
        "messages": [],
        "mode": "agent",
        "channel": "whatsapp",
        "escalation_summary": "",
        "customer_name": "",
        "email_subject": "",
        "email_last_message_id": "",
        "email_references": "",
        "escalations": [],
        "pending_first_message": "",
    }
    base.update(overrides)
    return base


class RuntimeSilenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_email_never_calls_claude(self):
        import agent

        state = _state()
        create = AsyncMock()
        with (
            patch.object(agent.store, "get_conversation", return_value=state),
            patch.object(agent.store, "save_conversation") as save,
            patch.object(agent.client.messages, "create", create),
        ):
            reply = await agent.chat(
                "ana@example.com",
                "Onde está a minha encomenda?",
                channel="email",
            )
        self.assertIsNone(reply)
        self.assertEqual(state["mode"], "human")
        self.assertEqual(state["channel"], "email")
        create.assert_not_called()
        save.assert_called()

    async def test_human_takeover_never_calls_claude(self):
        import agent

        state = _state(mode="human")
        create = AsyncMock()
        with (
            patch.object(agent.store, "get_conversation", return_value=state),
            patch.object(agent.store, "save_conversation"),
            patch.object(agent.client.messages, "create", create),
        ):
            reply = await agent.chat("351912338809", "ainda aí?", channel="whatsapp")
        self.assertIsNone(reply)
        create.assert_not_called()

    async def test_empty_alert_env_still_pings_desk(self):
        import notifications

        send = AsyncMock(return_value={"messages": [{"id": "wamid.test"}]})
        with (
            patch.object(notifications.settings, "alert_whatsapp_number", ""),
            patch.object(notifications.settings, "whatsapp_access_token", "tok"),
            patch.object(notifications.settings, "whatsapp_escalation_template", ""),
            patch.object(notifications.settings, "whatsapp_new_conversation_template", ""),
            patch.object(notifications.settings, "smtp_host", ""),
            patch.object(notifications.whatsapp, "send_message", send),
            patch.object(notifications.whatsapp, "send_template_message", AsyncMock()),
        ):
            result = await notifications.send_escalation_alert(
                "351913550000", "need human", "Ana", "1042"
            )
        self.assertEqual(result["status"], "sent")
        send.assert_awaited()
        self.assertEqual(send.await_args.args[0], "+351912338809")


if __name__ == "__main__":
    unittest.main()
