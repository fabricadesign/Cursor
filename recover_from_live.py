"""Pull every WhatsApp and email thread from the live admin inbox."""

from __future__ import annotations

import html as htmlmod
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

LIVE = "https://fabrica-support-agent.vercel.app"
ADMIN_PASSWORD = "fabrica_admin_2026"
LISBON = ZoneInfo("Europe/Lisbon")
OUT = Path(__file__).resolve().parent / "data" / "recovered_conversations.json"

MSG_SPLIT = re.compile(r'<div class="msg msg-(customer|agent|human)">')
LABEL_RE = re.compile(r'<div class="msg-label">.*?</div>', re.S)
TIME_RE = re.compile(r'<span class="msg-time">([^<]+)</span>')
IMG_RE = re.compile(
    r'<img src="data:([^;]+);base64,([^"]+)"',
    re.I,
)
NAME_RE = re.compile(r'<strong style="font-size:17px">([^<]*)</strong>')
CASE_RE = re.compile(r'<div class="info-bar"><strong>Case:</strong>\s*(.*?)</div>', re.S)
BOX_RE = re.compile(r'<div class="chat-box"[^>]*>(.*?)</div>\s*<form', re.S)


def _plain(fragment: str) -> str:
    fragment = IMG_RE.sub("", fragment)
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    return htmlmod.unescape(fragment).strip()


def _ts(label: str) -> str:
    m = TIME_RE.search(label or "")
    if not m:
        return ""
    raw = m.group(1).strip()
    try:
        dt = datetime.strptime(raw, "%d %b %Y, %H:%M").replace(tzinfo=LISBON)
        return dt.astimezone(ZoneInfo("UTC")).isoformat()
    except ValueError:
        return ""


def parse_thread(phone: str, page: str) -> dict:
    name = htmlmod.unescape(NAME_RE.search(page).group(1).strip()) if NAME_RE.search(page) else ""
    mode = "human" if ">Human mode</span>" in page else "agent"
    summary = ""
    cm = CASE_RE.search(page)
    if cm:
        summary = htmlmod.unescape(re.sub(r"<[^>]+>", "", cm.group(1))).strip()
    box_m = BOX_RE.search(page)
    body = box_m.group(1) if box_m else ""
    parts = MSG_SPLIT.split(body)
    messages = []
    # parts: [pre, role, html, role, html, ...]
    it = iter(parts[1:])
    for role in it:
        chunk = next(it, "")
        label_m = LABEL_RE.search(chunk)
        label = label_m.group(0) if label_m else ""
        rest = LABEL_RE.sub("", chunk, count=1)
        ts = _ts(label)
        img = IMG_RE.search(rest)
        text = _plain(rest)
        if role == "assistant" or role == "agent":
            messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
                "ts": ts,
            })
        elif role == "human":
            messages.append({"role": "human", "text": text, "ts": ts})
        else:
            msg = {"role": "customer", "text": text, "ts": ts}
            if img:
                msg["media"] = {"mime_type": img.group(1), "data": img.group(2)}
            messages.append(msg)
    return {
        "messages": messages,
        "mode": mode,
        "channel": "email" if "@" in phone else "whatsapp",
        "escalation_summary": summary,
        "customer_name": name,
        "email_subject": summary.replace("Email: ", "") if phone.find("@") >= 0 else "",
        "email_last_message_id": "",
        "email_references": "",
        "escalations": [],
        "pending_first_message": "",
    }


def fetch_all() -> dict[str, dict]:
    cookies = {"admin_token": ADMIN_PASSWORD}
    with httpx.Client(timeout=60.0, follow_redirects=True, cookies=cookies) as client:
        dash = client.get(f"{LIVE}/admin")
        dash.raise_for_status()
        ids = list(dict.fromkeys(re.findall(r'/admin/chat/([^"\'?]+)', dash.text)))
        print(f"Found {len(ids)} conversations on live admin", flush=True)

        recovered: dict[str, dict] = {}

        def one(cid: str):
            r = client.get(f"{LIVE}/admin/chat/{cid}")
            r.raise_for_status()
            return cid, parse_thread(cid, r.text)

        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(one, cid) for cid in ids]
            done = 0
            for fut in as_completed(futs):
                cid, state = fut.result()
                recovered[cid] = state
                done += 1
                if done % 20 == 0 or done == len(ids):
                    print(f"  {done}/{len(ids)}", flush=True)
        return recovered


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = fetch_all()
    payload = {
        "source": LIVE,
        "recovered_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        "count": len(data),
        "conversations": data,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False))
    wa = sum(1 for k in data if "@" not in k)
    em = sum(1 for k in data if "@" in k)
    msgs = sum(len(v.get("messages") or []) for v in data.values())
    print(f"Wrote {OUT} — {wa} WhatsApp, {em} email, {msgs} messages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
