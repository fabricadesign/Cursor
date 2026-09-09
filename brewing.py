"""Brewing guides / recipes for Fábrica Coffee Roasters.

Edit this file to refine the recipes Bea shares. The Chemex recipe is taken
from the Fábrica website; the others are reliable specialty-coffee standards
in the same style. Full guides: https://fabricacoffeeroasters.com/blogs/brewing
"""

BREWING_INFO_READY = True

BREWING_INFO = """
General guidance: use fresh, filtered water and freshly ground coffee. Tasting too
bitter → grind coarser or lower the temperature; too sour/weak → grind finer or
brew a little longer.

**Chemex** (Fábrica recipe)
- Ratio 1:15 — 20 g coffee : 300 g water (single) | 40 g : 600 g (double).
- Grind: medium-coarse (like coarse / rough sand). Water: 94 ºC.
- Rinse the paper filter with hot water and discard it. Add coffee, level it.
- Start timer, bloom with 50 g (single) / 100 g (double) over 15 s, spiralling from
  the centre out; wait 15 s.
- Pour the rest in a steady spiral. Target ~3 min total (single) / ~4 min (double).
- Remove filter, serve in pre-heated cups.

**Hario V60** (pour-over)
- Ratio ~1:16 — 15 g coffee : 250 g water. Grind: medium (like table salt). Water: 92–94 ºC.
- Rinse the paper filter, discard the water. Add coffee, level it.
- Bloom with ~40 g water for 30–45 s, then pour in slow spirals up to 250 g.
- Total brew time ~2:30–3:00.

**AeroPress**
- ~15–17 g coffee : 220–250 g water. Grind: medium-fine. Water: 80–85 ºC.
- Add coffee and water, stir gently, steep ~1:00–1:30, then press slowly over ~20–30 s.
- For a stronger, concentrated cup use less water and dilute to taste (Americano style).

**Moka pot** (stovetop)
- Fill the bottom chamber with hot water up to just below the safety valve.
- Fill the funnel basket with medium-fine grind, levelled — do NOT tamp.
- Assemble and put on medium-low heat with the lid open. When it starts to gurgle and
  the coffee turns pale/blond, remove from heat and cool the base to stop extraction.

**French press**
- Ratio ~1:16 — 30 g coffee : 500 g water. Grind: coarse. Water: 94–96 ºC.
- Add coffee and water, stir, steep 4 min, break the crust and skim, then plunge gently.

**Espresso**
- ~18 g in : 36 g out (1:2). Grind: fine. Water: 92–94 ºC. Shot time ~25–30 s.
- Adjust grind finer if the shot runs too fast/sour, coarser if too slow/bitter.
"""


def brewing_prompt_section() -> str:
    """Return the brewing-guides section for Bea's system prompt."""
    if not BREWING_INFO_READY:
        return ""
    return (
        "\n## Brewing guides & recipes\n"
        "When a customer asks how to brew, or for a recipe for a specific method or "
        "piece of gear (Chemex, V60, AeroPress, Moka pot, French press, espresso), give "
        "them the matching recipe below in a clear, friendly way (ratio, grind, water "
        "temperature, time, and the key steps). Ask which method/gear they use if it's "
        "not clear. Give the recipe directly in the chat — do not refer them to the "
        "website for it. Keep it concise for WhatsApp.\n"
        + BREWING_INFO
    )
