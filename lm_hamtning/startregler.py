# -*- coding: utf-8 -*-
"""Regler för automatikens start: känd skala och sökradie (2026-10-16).

Användaren granskade kartorna där lägessöket missar (kontroll/lagessok_underlag.py):
HÄG-102 s. 1 hade 1:5000 sparad från punktverktyget, fast skalstocken (läsningen)
sade 1:8000 och kartan är 1:8097 -- den sparade skalan gick före och lägessöket
provade bara skalor nära 1:5000; HÄG-118 s. 3-5 lånade 1:4000 från aktens andra
blad men är 1:8000. Starten ur aktens fastigheter var på HÄG-102 en enda yta på
1 ha, 2,4 km från kartans mitt: lägessöket letar bara 1,5 km. Användaren: "ja,
bygg båda rättelserna".

Lätt modul utan OpenCV: används både av pluginet (rektifiera_panel, i QGIS) och av
provbänken; automatisk läser bara fälten i uppdraget.
"""
from __future__ import annotations

import os
import re

# punktverktygets skala viker för skalstocken (läsningen) när de skiljer sig
SKALSTOCK_FORE = os.environ.get("HK_SKALSTOCK_FORE", "1") == "1"
SKALA_SKILLNAD = 0.10
# en skala lånad från aktens blad är ingen känd skala: alla standardskalor provas
LANAD_SKALA_ALLA = os.environ.get("HK_LANAD_SKALA_ALLA", "1") == "1"
# en liten startyta (aktens fastigheter under LITEN_ANDEL av kartans yta) säger lite
# om var kartans mitt ligger: lägessöket letar längre bort från den
LITEN_START = os.environ.get("HK_LITEN_START", "1") == "1"
LITEN_ANDEL = 0.10
LITEN_SOK_MAX_M = 5000.0
# Lägessökets vanliga radie är halva kartans kortsida, högst 1 500 m (automatisk.
# LAGE_SOK_M): den täcker redan små kartor. Regeln gäller bara när den går längre
# (varv 36: HÄG-95 s. 1, 1:2000, fick 700 m och valde fel vridning).
LAGE_SOK_TAK_M = 1500.0    # HÄG-118 s. 3-5: rätt läge 3,4 km från starten (helvarvsprovet: 3 km räckte inte)
# helvarvssöket: när vridningen är lånad (aktens blad, norr upp) får automatiken
# ett extra förslag från kartans start över hela varvet (alla standardskalor när skalan också är lånad)
# (HÄG-118 s. 3-5 och HÄG-68 s. 2-3 är ritade ett kvarts varv mot aktens andra blad)
HELVARV = os.environ.get("HK_HELVARV", "1") == "1"


# fyllnadsjord eller avradsland i titeln: marken ligger inte vid byarna (HÄG-26:
# "Fyllnadsjorden på Hammerdahls Sneogs Afradsland till ... Krogsta och Häggesta Byar")
AVRADSLAND = os.environ.get("HK_AVRADSLAND", "1") == "1"
AVRADSLAND_ORD = re.compile(r"fyllnads|a[fv]rads", re.IGNORECASE)


def osaker_start(titel: str) -> bool:
    """Säger titeln att marken inte ligger vid aktens byar (fyllnadsjord, avradsland)?"""
    return bool(AVRADSLAND and titel and AVRADSLAND_ORD.search(str(titel)))


# Traktens skilda delar som egna startförslag (2026-10-18): en trakt kan vara flera
# markbitar långt isär (ÖVERGÅRDEN: hemägorna och skogen 4 km isär), och traktens mitt
# hamnar då mellan dem (RÖD-66 s. 2 1 464 m fel, närmaste del 116 m). Av: starterna blev
# bättre (RÖD-66 s. 2 116 m, RÖD-63 s. 2–3 113/354 m) men lägessöket drog ändå iväg
# (483 m, 16°) och finjusteringen når inte 116 m (första steget 80 m); RÖD-64 rött ->
# gult på fel plats 5,9 km (en avlägsen del gav en trepunkt). Kvar till lägessöket
# klarar Rödön (bänken 2026-10-18, provbank_tdel).
TRAKTDELAR = os.environ.get("HK_TRAKTDELAR", "0") == "1"
TRAKTDEL_MINST_HA = 5.0      # mindre delar (en tomt, en holme) blir inga förslag
TRAKTDELAR_HOGST = 3


def trakt_start(varifran: str) -> bool:
    """Är starten traktens mitt (grovplaceringen ur traktlagret)? Då får alla blad i
    akten samma start, och ett blad i en serie ligger bredvid sina grannblad
    (Y61-22:2 s. 1-4, användaren 2026-10-17)."""
    return str(varifran or "").startswith("traktlager")


def vridning_saker(kalla: str) -> bool:
    """Är vridningen bladets egen (norrpilen, användaren) och inte lånad?"""
    k = str(kalla or "").strip().lower()
    return not (k.startswith("aktens blad") or k in ("norr upp", ""))


def kand_skala(info: dict, aktens: int = 0) -> tuple[int, bool, str]:
    """Kartans skala för automatiken ur `<karta>.json` (`info`, med läsningen) och
    aktens blad. -> (skala, säker, källa); skala 0 = okänd (automatiken provar
    alla standardskalor), säker False = lånad (automatiken provar dem också)."""
    info = info if isinstance(info, dict) else {}
    las = info.get("lasning") if isinstance(info.get("lasning"), dict) else {}
    try:
        js = int(info.get("skala") or 0)
    except (TypeError, ValueError):
        js = 0
    ls = las.get("skala")
    if (js and SKALSTOCK_FORE and str(info.get("skala_kalla") or "") == "punktverktyget"
            and isinstance(ls, (int, float)) and ls > 0 and abs(js / ls - 1) > SKALA_SKILLNAD):
        return int(round(ls)), True, "skalstocken (läsningen) före punktverktyget"
    if js:
        return js, True, str(info.get("skala_kalla") or "json")
    if aktens:
        return int(aktens), not LANAD_SKALA_ALLA, "aktens blad"
    return 0, True, ""


def start_sok_m(varifran: str, bredd_m: float, hojd_m: float, lanad_skala: bool = False) -> float:
    """Sökradien kring en start ur aktens fastigheter när ytan är liten mot
    kartan (0 = lägessökets vanliga). `varifran` är grovplaceringens text
    ("aktens fastigheter: 1 av 1 ytor, 1 ha"). Med lånad skala kan kartan vara en
    standardskala större (HÄG-118 s. 3-5: aktens 1:4000, kartan 1:8000)."""
    if not LITEN_START:
        return 0.0
    if lanad_skala:
        bredd_m, hojd_m = 2 * bredd_m, 2 * hojd_m
    m = re.search(r"aktens fastigheter: \d+ av \d+ ytor, (\d+) ha", varifran or "")
    if not m or bredd_m <= 0 or hojd_m <= 0:
        return 0.0
    if float(m.group(1)) * 1e4 >= LITEN_ANDEL * bredd_m * hojd_m:
        return 0.0
    r = min(LITEN_SOK_MAX_M, 0.5 * max(bredd_m, hojd_m))
    return r if r > LAGE_SOK_TAK_M else 0.0
