"""DPD Portugal tracking client — no API key required.

DPD's generic tracking.dpd.de REST endpoint doesn't work for Portuguese
parcels (bot-protected, resets the connection). Instead this scrapes DPD
Portugal's own public tracking page (tracking.dpd.pt), which server-renders
results for a plain GET request with a `reference` query param.

This is unofficial (no public API contract) and may break if DPD changes
their site's HTML. If DPD ever provides SOAP API credentials, switch to
dpd_client_soap.py instead.
"""

import ssl
import certifi
import httpx
from bs4 import BeautifulSoup

TRACKING_URL = "https://tracking.dpd.pt/track-and-trace"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# tracking.dpd.pt's server doesn't send its intermediate CA certificate
# (RapidSSL TLS RSA CA G1), only the leaf cert. Browsers tolerate this by
# fetching the intermediate themselves; strict clients like httpx/certifi
# don't, so we trust it explicitly here rather than skipping verification.
_RAPIDSSL_TLS_RSA_CA_G1 = """-----BEGIN CERTIFICATE-----
MIIEszCCA5ugAwIBAgIQCyWUIs7ZgSoVoE6ZUooO+jANBgkqhkiG9w0BAQsFADBh
MQswCQYDVQQGEwJVUzEVMBMGA1UEChMMRGlnaUNlcnQgSW5jMRkwFwYDVQQLExB3
d3cuZGlnaWNlcnQuY29tMSAwHgYDVQQDExdEaWdpQ2VydCBHbG9iYWwgUm9vdCBH
MjAeFw0xNzExMDIxMjI0MzNaFw0yNzExMDIxMjI0MzNaMGAxCzAJBgNVBAYTAlVT
MRUwEwYDVQQKEwxEaWdpQ2VydCBJbmMxGTAXBgNVBAsTEHd3dy5kaWdpY2VydC5j
b20xHzAdBgNVBAMTFlJhcGlkU1NMIFRMUyBSU0EgQ0EgRzEwggEiMA0GCSqGSIb3
DQEBAQUAA4IBDwAwggEKAoIBAQC/uVklRBI1FuJdUEkFCuDL/I3aJQiaZ6aibRHj
ap/ap9zy1aYNrphe7YcaNwMoPsZvXDR+hNJOo9gbgOYVTPq8gXc84I75YKOHiVA4
NrJJQZ6p2sJQyqx60HkEIjzIN+1LQLfXTlpuznToOa1hyTD0yyitFyOYwURM+/CI
8FNFMpBhw22hpeAQkOOLmsqT5QZJYeik7qlvn8gfD+XdDnk3kkuuu0eG+vuyrSGr
5uX5LRhFWlv1zFQDch/EKmd163m6z/ycx/qLa9zyvILc7cQpb+k7TLra9WE17YPS
n9ANjG+ECo9PDW3N9lwhKQCNvw1gGoguyCQu7HE7BnW8eSSFAgMBAAGjggFmMIIB
YjAdBgNVHQ4EFgQUDNtsgkkPSmcKuBTuesRIUojrVjgwHwYDVR0jBBgwFoAUTiJU
IBiV5uNu5g/6+rkS7QYXjzkwDgYDVR0PAQH/BAQDAgGGMB0GA1UdJQQWMBQGCCsG
AQUFBwMBBggrBgEFBQcDAjASBgNVHRMBAf8ECDAGAQH/AgEAMDQGCCsGAQUFBwEB
BCgwJjAkBggrBgEFBQcwAYYYaHR0cDovL29jc3AuZGlnaWNlcnQuY29tMEIGA1Ud
HwQ7MDkwN6A1oDOGMWh0dHA6Ly9jcmwzLmRpZ2ljZXJ0LmNvbS9EaWdpQ2VydEds
b2JhbFJvb3RHMi5jcmwwYwYDVR0gBFwwWjA3BglghkgBhv1sAQEwKjAoBggrBgEF
BQcCARYcaHR0cHM6Ly93d3cuZGlnaWNlcnQuY29tL0NQUzALBglghkgBhv1sAQIw
CAYGZ4EMAQIBMAgGBmeBDAECAjANBgkqhkiG9w0BAQsFAAOCAQEAGUSlOb4K3Wtm
SlbmE50UYBHXM0SKXPqHMzk6XQUpCheF/4qU8aOhajsyRQFDV1ih/uPIg7YHRtFi
CTq4G+zb43X1T77nJgSOI9pq/TqCwtukZ7u9VLL3JAq3Wdy2moKLvvC8tVmRzkAe
0xQCkRKIjbBG80MSyDX/R4uYgj6ZiNT/Zg6GI6RofgqgpDdssLc0XIRQEotxIZcK
zP3pGJ9FCbMHmMLLyuBd+uCWvVcF2ogYAawufChS/PT61D9rqzPRS5I2uqa3tmIT
44JhJgWhBnFMb7AGQkvNq9KNS9dd3GWc17H/dXa1enoxzWjE0hBdFjxPhUb0W3wi
8o34/m8Fxw==
-----END CERTIFICATE-----"""


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=certifi.where())
    context.load_verify_locations(cadata=_RAPIDSSL_TLS_RSA_CA_G1)
    return context


async def track_parcel(tracking_number: str) -> dict | None:
    """Track a parcel via DPD Portugal's public tracking page.

    Returns None if the parcel isn't found or the page can't be reached/parsed.
    """
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, verify=_ssl_context()) as client:
        try:
            resp = await client.get(
                TRACKING_URL,
                params={"reference": tracking_number},
                headers=_HEADERS,
            )
            resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError):
            return None

    return _parse_tracking_page(resp.text, tracking_number)


def _parse_tracking_page(html: str, tracking_number: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")

    if soup.find(class_="current-status-notfound"):
        return None

    status_block = soup.find(class_="current-status")
    if not status_block:
        return None

    description = status_block.find(class_="current-description")
    date = status_block.find(class_="current-date")

    events = []
    for row in soup.select("table.table tbody tr"):
        cells = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cells) >= 4:
            events.append({
                "code": cells[0],
                "date": cells[1],
                "time": cells[2],
                "description": cells[3],
            })

    return {
        "reference": tracking_number,
        "status": description.get_text(strip=True) if description else "Unknown",
        "status_date": date.get_text(strip=True) if date else "",
        "events": events,
    }


def format_tracking_info(data: dict) -> dict:
    """Extract key tracking fields into a clean summary for the agent."""
    events = data.get("events", [])
    latest = events[0] if events else {}
    return {
        "tracking_number": data.get("reference", "N/A"),
        "status": data.get("status", "Unknown"),
        "latest_event_date": latest.get("date") or data.get("status_date") or "N/A",
        "latest_event_time": latest.get("time", ""),
        "total_events": len(events),
    }
