"""Physical shop information for Fábrica Coffee Roasters.

Edit this file whenever shop details change (hours, address, etc.).
The content is injected into Bea's knowledge so she can answer questions
about the shops. Source: https://fabricacoffeeroasters.com/pages/find-a-store
"""

SHOPS_INFO_READY = True

SHOPS_INFO = """
**Lisbon**
- Fábrica Avenida — Rua das Portas de Santo Antão 136, 1150-269 Lisboa. Open Monday–Sunday, 9:00–17:00.
- Fábrica Chiado — Rua das Flores 63, 1200-193 Lisboa. Open Monday–Sunday, 9:00–17:00.
- Fábrica Comércio — Rua do Comércio 111, 1100-150 Lisboa. Open Monday–Sunday, 9:00–17:00.
- Fábrica Santos — Avenida D. Carlos I 110-114, 1200-267 Lisboa. Open Monday–Sunday, 9:00–17:00.
- Fábrica S. Mamede — R. de São Mamede 28C, 1100-006 Lisboa. Open Monday–Sunday, 9:00–17:00.

**Cascais**
- Fábrica Cascais — Av. Valbom 26B, 2750-355 Cascais. Open Monday–Sunday, 8:30–17:00.
- Mercado de Cascais — Rua Padre Moisés da Silva 29, 2750-437 Cascais. Open Wednesdays, Saturdays and Sundays, 8:00–15:00.

**Sintra (Roastery & Cafeteria)**
- Rua dos Selões 16, Armazém B, Terrugem, 2705-898 Sintra. Open Monday–Friday 9:30–17:00, Saturday 9:30–13:30.

Full list with maps: https://fabricacoffeeroasters.com/pages/find-a-store
"""


def shops_prompt_section() -> str:
    """Return the shop-info section for Bea's system prompt, if ready."""
    if not SHOPS_INFO_READY:
        return ""
    return (
        "\n## Our physical shops\n"
        "We have several shops in Lisbon and Cascais, plus a roastery in Sintra. "
        "When customers ask about store locations, opening hours, or visiting us, "
        "share the relevant details below. If someone asks which shop is nearest, "
        "ask where they are. If asked about a detail not listed (e.g. phone number), "
        "say you're not sure and point them to the store page — do not guess.\n"
        + SHOPS_INFO
    )
