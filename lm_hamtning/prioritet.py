"""Vilka åtgärder som går först i urvalet och i arbetslistan.

Användaren 2026-09-29: laga skifte, storskifte, avvittring (sockenkartan om den
finns) och skattläggning -- det är oftast på de kartorna man hittar förmodade
lämningar. Övriga åtgärder (avsöndring, ägoutbyte, avmätning ...) kommer efter.

En akt har ofta flera åtgärder ("Avsöndring; Laga skifte": HÄG-60, HÄG-122),
så alla räknas, inte bara den första. "Storskifte på inägor" är ett storskifte.
"""
from __future__ import annotations

PRIORITERADE = ("laga skifte", "storskifte", "avvittring", "skattläggning")


def prioriterad(atgarder) -> bool:
    """`atgarder`: registrets text ("Avsöndring; Laga skifte") eller en lista."""
    if not atgarder:
        return False
    if isinstance(atgarder, str):
        atgarder = atgarder.split(";")
    return any(p in a.strip().lower() for a in atgarder for p in PRIORITERADE)


# Urvalet i Gallra (användaren 2026-10-01: "en lista på vilka sorters kartor man
# vill ha"): en åtgärdstyp i taget, laga skifte först (KRAV avsnitt 6).
OVRIGA = "övriga"
TYPER = (("laga skifte", "Laga skifte"), ("storskifte", "Storskifte"),
         ("avvittring", "Avvittring"), ("skattläggning", "Skattläggning"),
         (OVRIGA, "Övriga åtgärder"))

# Förklaringar som verktygstips på åtgärdsraden (användaren 2026-10-26: folk som inte är
# vana ska förstå), kort och utan årtal som kan diskuteras.
FORKLARING = {
    "laga skifte": "Laga skifte (1800-talet fram till 1920-talet): hela byns mark delades om i "
                   "sammanhängande ägor. De mest detaljerade kartorna, med ägogränser, ofta hus "
                   "och odlingsmark. Vanligen det bästa valet.",
    "storskifte": "Storskifte (1700-talets mitt till 1820-talet): det första stora skiftet, byns "
                  "tegar slogs ihop till större ägor. Kartor över hela byn.",
    "avvittring": "Avvittring (mest i Norrland): kronans mark skildes från byarnas. Stora kartor "
                  "över utmarken och byarnas gränser.",
    "skattläggning": "Skattläggning: byns jord mättes och värderades för skatten, ofta på 1600- "
                     "och 1700-talen. Kartor över inägorna.",
    OVRIGA: "Övriga åtgärder: hemmansklyvning, ägobyte, avsöndring, laga delning med mera. "
            "Ofta kartor över en del av byn.",
}


def vald(atgarder, valda) -> bool:
    """Har akten någon av de valda åtgärdstyperna? `valda` är nycklar ur TYPER;
    "övriga" betyder en åtgärd som inte är någon av de fyra prioriterade.
    En akt utan åtgärd släpps igenom (den kan inte bedömas här)."""
    if not atgarder:
        return True
    if isinstance(atgarder, str):
        atgarder = atgarder.split(";")
    for a in (x.strip().lower() for x in atgarder):
        typ = next((p for p in PRIORITERADE if p in a), OVRIGA)
        if typ in valda:
            return True
    return False
