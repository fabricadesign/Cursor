"""Policy checks that do not need live API keys."""

import unittest

from guardrails import (
    customer_asked_for_contact,
    scrub_support_mailbox_deflection,
    should_agent_speak,
)


class GuardrailTests(unittest.TestCase):
    def test_strips_support_mailbox_on_whatsapp(self):
        reply = (
            "Não consigo ver a encomenda daqui. "
            "Por favor envie o seu pedido para support@fabricacoffeeroasters.com."
        )
        cleaned, repaired = scrub_support_mailbox_deflection(
            reply, "Onde está a minha encomenda?"
        )
        self.assertTrue(repaired)
        self.assertNotIn("support@fabricacoffeeroasters.com", cleaned.lower())
        self.assertIn("encomenda", cleaned.lower())

    def test_keeps_mailbox_when_customer_asks_for_email(self):
        reply = "O nosso email é support@fabricacoffeeroasters.com."
        cleaned, repaired = scrub_support_mailbox_deflection(
            reply, "Qual é o vosso email?"
        )
        self.assertFalse(repaired)
        self.assertIn("support@fabricacoffeeroasters.com", cleaned)

    def test_empty_bounce_gets_stay_here_copy(self):
        reply = "Please email support@fabricacoffeeroasters.com for help."
        cleaned, repaired = scrub_support_mailbox_deflection(reply, "Hi")
        self.assertTrue(repaired)
        self.assertNotIn("@", cleaned)
        self.assertIn("WhatsApp", cleaned)

    def test_contact_question_detector(self):
        self.assertTrue(customer_asked_for_contact("What's your email?"))
        self.assertFalse(customer_asked_for_contact("Where is order 1042?"))

    def test_agent_does_not_speak_on_email(self):
        self.assertFalse(should_agent_speak("email", "agent"))
        self.assertFalse(should_agent_speak("email", "human"))

    def test_agent_silent_after_human_takeover(self):
        self.assertFalse(should_agent_speak("whatsapp", "human"))
        self.assertTrue(should_agent_speak("whatsapp", "agent"))


if __name__ == "__main__":
    unittest.main()
