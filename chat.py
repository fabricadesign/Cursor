"""Terminal chat mode — test the agent without WhatsApp.

Usage:
    python chat.py
"""

import asyncio
import sys
import os

os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

import agent


async def main():
    print("=" * 50)
    print("Fábrica Coffee Roasters — Support Agent")
    print("Terminal Test Mode")
    print("=" * 50)
    print("Type your messages below (PT or EN).")
    print("Type 'quit' to exit.\n")

    phone = "test_terminal_user"

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "sair"):
            break

        try:
            reply = await agent.chat(phone, user_input)
            print(f"\nAgent: {reply}\n")
        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    asyncio.run(main())
