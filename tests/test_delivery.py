"""24h WhatsApp window, delivery errors, and the inbox fail banner."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import unittest

import store
import whatsapp
from config import settings
from main import _fail_banner_html, _is_reengagement_error, _queue_outbound_text


def _ts(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


class WindowAndBannerTests(unittest.TestCase):
    def test_window_closed_with_no_customer_messages(self):
        self.assertFalse(store.customer_window_open({"messages": []}))
        self.assertFalse(
            store.customer_window_open(
                {"messages": [{"role": "human", "text": "Olá", "ts": _ts(0)}]}
            )
        )

    def test_window_open_after_recent_customer_message(self):
        state = {"messages": [{"role": "customer", "text": "hi", "ts": _ts(1)}]}
        self.assertTrue(store.customer_window_open(state))

    def test_window_closed_after_stale_customer_message(self):
        state = {"messages": [{"role": "customer", "text": "hi", "ts": _ts(25)}]}
        self.assertFalse(store.customer_window_open(state))

    def test_summary_empty_thread_does_not_crash(self):
        summary = store._summary_from_state({"messages": [], "mode": "human"})
        self.assertEqual(summary["last_delivery"], "")
        self.assertEqual(summary["last_delivery_error"], "")
        self.assertEqual(summary["last_customer_ts"], "")

    def test_summary_keeps_delivery_error(self):
        state = {
            "messages": [
                {
                    "role": "human",
                    "text": "Olá",
                    "ts": _ts(0),
                    "delivery": "failed",
                    "delivery_error": "Re-engagement message (131047)",
                }
            ]
        }
        summary = store._summary_from_state(state)
        self.assertEqual(summary["last_delivery"], "failed")
        self.assertIn("131047", summary["last_delivery_error"])

    def test_liz_banner_does_not_say_please_resend(self):
        html = _fail_banner_html(
            {
                "last_delivery": "failed",
                "last_delivery_error": "",
                "last_customer_text": "",
                "last_customer_ts": "",
            }
        )
        self.assertIn("24h window", html)
        self.assertIn("do not resend", html.lower())
        self.assertNotIn("please resend", html.lower())

    def test_reengagement_error_banner(self):
        html = _fail_banner_html(
            {
                "last_delivery": "failed",
                "last_delivery_error": "Re-engagement message (131047)",
                "last_customer_text": "old hello",
                "last_customer_ts": _ts(1),
            }
        )
        self.assertIn("24h window", html)
        self.assertNotIn("please resend", html.lower())

    def test_country_restriction_shows_real_error(self):
        html = _fail_banner_html(
            {
                "last_delivery": "failed",
                "last_delivery_error": "Business account is restricted from messaging users in this country.",
                "last_customer_text": "oi",
                "last_customer_ts": _ts(1),
            }
        )
        self.assertIn("restricted", html.lower())
        self.assertNotIn("24h window", html)

    def test_queue_when_window_closed(self):
        state = store._default_state()
        self.assertTrue(_queue_outbound_text(state, "Olá estimado cliente"))
        self.assertEqual(state["pending_first_message"], "Olá estimado cliente")

    def test_does_not_queue_when_window_open(self):
        state = store._default_state()
        state["messages"] = [{"role": "customer", "text": "hi", "ts": _ts(0.5)}]
        self.assertFalse(_queue_outbound_text(state, "Olá"))
        self.assertEqual(state["pending_first_message"], "")

    def test_extract_statuses_includes_code(self):
        body = {
            "entry": [{
                "changes": [{
                    "value": {
                        "statuses": [{
                            "id": "wamid.HBgM",
                            "status": "failed",
                            "recipient_id": "351924175288",
                            "errors": [{
                                "code": 131047,
                                "title": "Re-engagement message",
                                "message": "Message failed to send because more than 24 hours have passed",
                            }],
                        }]
                    }
                }]
            }]
        }
        statuses = whatsapp.extract_statuses(body)
        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0]["status"], "failed")
        self.assertEqual(statuses[0]["error_code"], 131047)
        self.assertIn("Re-engagement", statuses[0]["error"])
        self.assertIn("131047", statuses[0]["error"])
        self.assertTrue(_is_reengagement_error(statuses[0]["error"]))


class StoreDeliveryTests(unittest.TestCase):
    def setUp(self):
        store._memory_store.clear()
        self.patcher = patch.object(store, "_get_redis", return_value=None)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        store._memory_store.clear()

    def test_update_message_delivery_stores_error(self):
        phone = "351924175288"
        state = store._default_state()
        state["messages"].append({
            "role": "human",
            "text": "Olá",
            "ts": _ts(0),
            "wamid": "wamid.liz",
            "delivery": "sent",
        })
        store.save_conversation(phone, state)
        ok = store.update_message_delivery(
            phone, "wamid.liz", "failed", error="Re-engagement message (131047)"
        )
        self.assertTrue(ok)
        saved = store.get_conversation(phone)
        self.assertEqual(saved["messages"][0]["delivery"], "failed")
        self.assertIn("131047", saved["messages"][0]["delivery_error"])
        listed = store.list_all()
        self.assertEqual(listed[0]["last_delivery"], "failed")
        self.assertIn("131047", listed[0]["last_delivery_error"])


class AdminSendPathTests(unittest.TestCase):
    def setUp(self):
        store._memory_store.clear()
        self.boot = patch.object(store, "load_disk_backup_if_empty", return_value=0)
        self.boot.start()
        self.redis = patch.object(store, "_get_redis", return_value=None)
        self.redis.start()
        self.send = patch.object(whatsapp, "send_message", new_callable=AsyncMock)
        self.send_mock = self.send.start()
        self.send_mock.return_value = {"messages": [{"id": "wamid.ok"}]}

    def tearDown(self):
        self.send.stop()
        self.redis.stop()
        self.boot.stop()
        store._memory_store.clear()

    def _client(self):
        from fastapi.testclient import TestClient
        from main import app

        return TestClient(app)

    def _login(self, client):
        r = client.post(
            "/admin/login",
            data={"password": settings.admin_password},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)

    def test_new_conversation_queues_instead_of_calling_graph(self):
        client = self._client()
        self._login(client)
        r = client.post(
            "/admin/new",
            data={
                "phone": "351924175288",
                "name": "Liz Coolen",
                "message": "Olá estimado cliente, sou a Bea.",
            },
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)
        self.assertIn("held=1", r.headers.get("location", ""))
        self.send_mock.assert_not_called()
        state = store.get_conversation("351924175288")
        self.assertEqual(state["mode"], "human")
        self.assertIn("Bea", state["pending_first_message"])
        self.assertEqual(state["messages"], [])

    def test_send_queued_does_not_hit_graph_while_window_closed(self):
        phone = "351924175288"
        state = store._default_state()
        state["mode"] = "human"
        state["pending_first_message"] = "Olá"
        store.save_conversation(phone, state)
        client = self._client()
        self._login(client)
        r = client.post(f"/admin/chat/{phone}/send-queued", follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn("held=1", r.headers.get("location", ""))
        self.send_mock.assert_not_called()
        self.assertEqual(store.get_conversation(phone)["pending_first_message"], "Olá")

    def test_send_goes_out_when_customer_wrote_recently(self):
        phone = "351912338809"
        state = store._default_state()
        state["messages"] = [{"role": "customer", "text": "oi", "ts": _ts(0.2)}]
        store.save_conversation(phone, state)
        client = self._client()
        self._login(client)
        r = client.post(
            f"/admin/chat/{phone}/send",
            data={"message": "Já estou a tratar disso."},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)
        self.send_mock.assert_awaited()
        saved = store.get_conversation(phone)
        self.assertEqual(saved["mode"], "human")
        self.assertEqual(saved["messages"][-1]["text"], "Já estou a tratar disso.")


if __name__ == "__main__":
    unittest.main()
