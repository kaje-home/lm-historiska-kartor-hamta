"""Behallna kartsidor till arkivet (avsnitt 6, Nedladdning).

For varje akt vars senaste beslut ar `behall`: aktens KARTSIDOR -- inte
textsidorna -- hamtas som TIFF, lagras med ZSTD och kontrolleras pixel for
pixel (arkivfil.py), och fors in i registret. Sidor som redan har en fil
hoppas over, sa en avbruten korning fortsatter dar den slutade.

Filnamn efter mall, forval `{atgard}_{ar}_{beteckning}_{socken}_s{sida}.tif`,
i `<arkiv>/kartor/<socken>/`. Tecken som Windows inte tal byts mot `-`
(`Y22-2:1` -> `Y22-2-1`), mellanslag i atgarden likasa (`Laga-skifte`), sa
att understrecken skiljer falten at.

En sida som ligger pa disk men saknas i registret -- en korning som dog
mellan lagringen och registreringen -- registreras som den ar. Den har
redan klarat pixelkontrollen, for den far sitt namn forst efter den.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import arkivfil

MALL = "{atgard}_{ar}_{beteckning}_{socken}_s{sida}.tif"
_OTILLATET = re.compile(r'[\\/:*?"<>|\s]+')


def _rent(s: str) -> str:
    return _OTILLATET.sub("-", s.strip()).strip("-") or "okänd"


def filnamn(akt, sida, mall: str = MALL) -> str:
    """`akt` och `sida` ar registerrader (eller ordbocker med samma falt)."""
    atgard = (akt["atgard"] or "").split(";")[0]
    return mall.format(atgard=_rent(atgard), ar=akt["ar"] or "u.å.",
                       beteckning=_rent(akt["beteckning"]),
                       socken=_rent(akt["socken"] or ""), sida=sida["lopnr"])


def relativ_sokvag(akt, sida, mall: str = MALL) -> str:
    return "/".join(("kartor", _rent(akt["socken"] or ""), filnamn(akt, sida, mall)))


@dataclass
class Nedladdat:
    hamtade: list[str] = field(default_factory=list)      # relativa sokvagar
    aterfunna: list[str] = field(default_factory=list)
    fel: list[str] = field(default_factory=list)
    byte: int = 0
    avbrutet: bool = False
    textakter: int = 0                                     # textakter sparade (steg.ladda_ned)
    textakt_fel: list[str] = field(default_factory=list)


def ladda_ned(arkiv: str, cache: str, klient, register, mall: str = MALL,
              framsteg=None, avbruten=None) -> Nedladdat:
    ut = Nedladdat()
    arbete = [(a, s) for a in register.behallna_akter()
              for s in register.kartsidor_utan_fil(a["nyckel"])]
    for i, (a, s) in enumerate(arbete):
        if avbruten is not None and avbruten():
            ut.avbrutet = True
            break
        rel = relativ_sokvag(a, s, mall)
        mal = os.path.join(arkiv, *rel.split("/"))
        if framsteg:
            framsteg(f"{a['beteckning']} s. {s['lopnr']} ({i + 1} av {len(arbete)})",
                     i / max(len(arbete), 1))
        try:
            if os.path.exists(mal):
                l = arkivfil.befintlig(mal)
                ut.aterfunna.append(rel)
            else:
                tmp = os.path.join(cache, "tiff", f"{a['bas']}_{a['ktun']}_"
                                                  f"{s['handling']}_{s['sidn']}.tiff")
                klient.hamta_tiff(a["bas"], a["ktun"], s["handling"], s["sidn"], tmp)
                l = arkivfil.lagra_tiff(tmp, mal)
                ut.hamtade.append(rel)
                ut.byte += l.storlek_byte
            register.spara_fil(s["guid"], rel, l.format, l.storlek_byte, l.sha256,
                               l.bredd_px, l.hojd_px)
        except Exception as e:          # en sida far inte stoppa resten
            ut.fel.append(f"{a['beteckning']} s. {s['lopnr']}: {str(e).splitlines()[0]}")
    if framsteg:
        framsteg("klart", 1.0)
    return ut
