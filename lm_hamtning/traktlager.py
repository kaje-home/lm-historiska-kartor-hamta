"""Ett traktlager fran annan kalla, gjort anvandbart (avsnitt 5).

Byggt for det befintliga lagret for Jamtland (`Trakter i Jämtland.gdb`,
`ay_23_Dissolve`), men utan att anta dess faltnamn: anvandaren anger vilket
falt som ar traktnamn och, om det finns, vilket som ar socken.

Tre saker maste goras innan ett sadant lager duger:

* **Dela pa socken.** Jamtlandslagret ar upplost pa namn over hela lanet --
  trakter med samma namn i olika socknar ar ett multipolygonobjekt. Osteråsen
  har bara 41 % av sin yta i Haggenas. Varje objekt skars darfor mot Socken
  och stad, och varje del far den sockens namn och kod. Har lagret ett
  sockenfalt anvands det i stallet.
* **Skrapet bort.** Tomt namn, `1>1`, `OUTRETT OMRÅDE`.
* **Kvarteren bort.** Kvartersnamnen (`ONKEL ADAM`, `RÖDA LYKTAN`) ligger i
  Ostersund. De kanns igen pa att de ligger i en *stad* i Socken och stad
  (`sockenstadtyp` 2), inte pa storleken: Duveds skans ar 1 078 m2 men en
  riktig trakt.

**Skarvor bort.** Traktlagrets granser och Socken och stads gar inte exakt
lika, sa delningen ger remsor langs sockengranserna: Brevåg far 0 m2 i
Haggenas, Raftälven 1,6 ha (0,05 %). Provat 2026-09-29 over fem socknar
(270 delar): skarvorna ligger under 2 000 m2 och 0,01 %, sedan kommer delar
pa flera hektar. En del som ar under `SKARVA_ANDEL` av objektet OCH under
`SKARVA_M2` raknas som skarva. Riktiga sma trakter paverkas inte -- de ligger
hela i en socken, andel 100 %. Skarvorna redovisas, de forsvinner inte tyst.

Lagret lases med GDAL och andras aldrig. Resultatet ar ytor i minnet;
var de sparas avgors nar Gallra byggs.

Socken och stad: `sockenstadnamn`, `sockenstadkod`, `sockenstadtyp`
(1 socken, 2 stad). Samma socken kan ha flera ytor (`omradesnummer`); de
slas ihop per kod.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SKRAP = {"", "1>1", "OUTRETT OMRÅDE"}
STAD = 2
SKARVA_ANDEL = 0.01
SKARVA_M2 = 50_000


@dataclass
class Traktyta:
    namn: str               # som i lagret
    socken: str
    sockenkod: str
    wkb: bytes = field(repr=False)
    yta_m2: float = 0.0
    andel: float = 1.0      # andel av lagrets objekt som hamnade i socknen


@dataclass
class Traktlager:
    ytor: list[Traktyta] = field(default_factory=list)
    skrap: list[str] = field(default_factory=list)
    i_stad: list[str] = field(default_factory=list)
    utanfor: list[str] = field(default_factory=list)   # i ingen socken alls
    skarvor: list[Traktyta] = field(default_factory=list)

    def i_socken(self, socken: str) -> list[Traktyta]:
        s = socken.casefold()
        return [y for y in self.ytor if y.socken.casefold() == s]


def _socknar(sokvag: str, namn: set[str] | None):
    """sockenkod -> (namn, typ, geometri), sammanslagna per kod."""
    from osgeo import ogr
    ds = ogr.Open(sokvag)
    lager = ds.GetLayer("sockenstad") or ds.GetLayer(0)
    if namn:
        lista = ",".join("'" + n.replace("'", "''") + "'" for n in namn)
        lager.SetAttributeFilter(f"sockenstadnamn IN ({lista})")
    ut: dict[str, list] = {}
    for f in lager:
        kod = f["sockenstadkod"]
        g = f.GetGeometryRef().Clone()
        if kod in ut:
            ut[kod][2] = ut[kod][2].Union(g)
        else:
            ut[kod] = [f["sockenstadnamn"], f["sockenstadtyp"], g]
    return ut, lager.GetSpatialRef().Clone() if lager.GetSpatialRef() else None


def las(sokvag: str, lagernamn: str | None, traktfalt: str,
        socken_och_stad: str, sockenfalt: str | None = None,
        bara_socknar: set[str] | None = None) -> Traktlager:
    """Las traktlagret och dela det pa socken.

    `bara_socknar` begransar till nagra socknar (namn som i Socken och
    stad) -- for prov, och nar bara arbetsomradets socknar behovs. Delar
    utanfor dem raknas da inte som `utanfor`.
    """
    from osgeo import gdal
    gdal.UseExceptions()
    # Jamtlandslagrets storsta objekt har hundratals delar, och GDAL:s
    # sortering av ringar blir da mycket langsam. ESRI:s halringar gar
    # moturs, sa ONLY_CCW ar sakert for en filgeodatabas.
    # Sjalvkorsande ringar finns i lagret; de lagas med MakeValid, och GDAL:s
    # varning om var de ligger ar inget anvandaren kan gora nagot at.
    with gdal.config_options({"OGR_ORGANIZE_POLYGONS": "ONLY_CCW"}), \
            gdal.quiet_errors():
        return _las(sokvag, lagernamn, traktfalt, socken_och_stad,
                    sockenfalt, bara_socknar)


def _las(sokvag, lagernamn, traktfalt, socken_och_stad, sockenfalt,
         bara_socknar) -> Traktlager:
    from osgeo import ogr, osr

    ds = ogr.Open(sokvag, 0)
    lager = ds.GetLayer(lagernamn) if lagernamn else ds.GetLayer(0)
    socknar, srs_s = _socknar(socken_och_stad, bara_socknar)
    srs_t = lager.GetSpatialRef()
    omvandla = None
    if srs_s is not None and srs_t is not None and not srs_t.IsSame(srs_s):
        srs_t.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        srs_s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        omvandla = osr.CoordinateTransformation(srs_t, srs_s)

    if bara_socknar:
        # Bara objekt som kan rora socknarna behover lasas.
        hela = None
        for _, _, g in socknar.values():
            hela = g.Clone() if hela is None else hela.Union(g)
        if hela is not None and omvandla is None:
            lager.SetSpatialFilter(hela)

    ut = Traktlager()
    for f in lager:
        namn = (f[traktfalt] or "").strip()
        if namn.upper() in SKRAP:
            ut.skrap.append(namn)
            continue
        g = f.GetGeometryRef()
        if g is None or g.IsEmpty():
            ut.skrap.append(namn)
            continue
        g = g.Clone()
        if omvandla is not None:
            g.Transform(omvandla)
        if not g.IsValid():
            g = g.MakeValid()
        hel_yta = g.GetArea() or 1.0

        if sockenfalt:
            s = (f[sockenfalt] or "").strip()
            ut.ytor.append(Traktyta(namn, s, "", g.ExportToWkb(), hel_yta, 1.0))
            continue

        traffad = False
        for kod, (snamn, typ, sg) in socknar.items():
            if not g.Intersects(sg):
                continue
            del_ = g.Intersection(sg)
            yta = del_.GetArea() if del_ is not None else 0.0
            if yta <= 0:
                continue
            traffad = True
            if typ == STAD:
                ut.i_stad.append(namn)
                continue
            y = Traktyta(namn, snamn, kod, del_.ExportToWkb(), yta, yta / hel_yta)
            if y.andel < SKARVA_ANDEL and y.yta_m2 < SKARVA_M2:
                ut.skarvor.append(y)
            else:
                ut.ytor.append(y)
        if not traffad and not bara_socknar:
            ut.utanfor.append(namn)
    return ut
