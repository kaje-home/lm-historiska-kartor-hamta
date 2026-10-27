# Kopierad ur LM Fältunderlag (lm_faltunderlag/verktyg/kontroll.py, commit 374b15d) 2026-10-08:
# pluginet ska gå utan Fältunderlaget (KRAV avsnitt 2). Rättningar görs i båda.
"""Verifiera att ett steg faktiskt levererade det det sager.

Detta ar den viktigaste modulen i pluginet, och den finns pa grund av avsnitt 8:
under kalibreringen aterkom samma monster tre ganger -- verktyget rapporterade
framgang och levererade ingenting.

  * `processing.run()` returnerade `Process completed successfully` med en
    OUTPUT-sokvag utan att skapa filen (tomt `--filter=`).
  * pdal_wrench skrev en avhuggen VPC-fil pa 4277 byte.
  * Projektbygget satte fel CRS utan att klaga.

Inget av det syntes i returvardet. Anropa darfor `kontrollera_*` efter varje
steg som skriver en fil, och lat kedjan braka har i stallet for att uppdaget
ska goras pa Toughbooken i falt.
"""
from __future__ import annotations

import json
import os
import time
import re
import unicodedata


class Levererades_inte(Exception):
    """Ett steg rapporterade framgang men filen ar inte anvandbar."""


def _finns(sokvag: str, minsta_byte: int) -> None:
    if not os.path.exists(sokvag):
        raise Levererades_inte(
            f"{os.path.basename(sokvag)} skapades aldrig. Steget rapporterade "
            f"framgang, sa returvardet gar inte att lita pa -- se avsnitt 8."
        )
    n = os.path.getsize(sokvag)
    if n < minsta_byte:
        raise Levererades_inte(
            f"{os.path.basename(sokvag)} ar {n} byte, vilket ar for lite for att "
            f"vara komplett (vantade minst {minsta_byte})."
        )


def kontrollera_raster(sokvag: str, *, minsta_byte: int = 1024,
                       vantade_band: int | None = None,
                       vantad_crs: str | None = None) -> None:
    """Raster: finns, gar att oppna, har band och data."""
    from osgeo import gdal
    gdal.UseExceptions()
    _finns(sokvag, minsta_byte)
    try:
        ds = gdal.Open(sokvag)
    except Exception as e:
        raise Levererades_inte(f"{os.path.basename(sokvag)} gar inte att oppna: {e}")
    if ds is None:
        raise Levererades_inte(f"{os.path.basename(sokvag)} gar inte att oppna.")
    if ds.RasterXSize < 1 or ds.RasterYSize < 1:
        raise Levererades_inte(
            f"{os.path.basename(sokvag)} har storleken "
            f"{ds.RasterXSize}x{ds.RasterYSize}. Nollstora rader kommer typiskt "
            f"av att en utbredning inte tolkades -- se FILTER_EXTENT i avsnitt 3."
        )
    if vantade_band is not None and ds.RasterCount != vantade_band:
        raise Levererades_inte(
            f"{os.path.basename(sokvag)} har {ds.RasterCount} band, vantade "
            f"{vantade_band}. rvt_multi_hillshade ger 16 band och maste vagas "
            f"samman -- se avsnitt 7."
        )
    if vantad_crs is not None:
        wkt = ds.GetProjection()
        if not wkt:
            raise Levererades_inte(f"{os.path.basename(sokvag)} saknar CRS.")
    ds = None


def kontrollera_vpc(sokvag: str) -> int:
    """VPC: giltig JSON hela vagen, och minst en ruta. Returnerar antal rutor.

    pdal_wrench kan skriva en avhuggen fil som slutar mitt i en token. Den ser
    ut att finnas och har rimlig storlek -- bara en full JSON-tolkning avslojar
    den.
    """
    _finns(sokvag, 256)
    try:
        with open(sokvag, encoding="utf-8") as f:
            d = json.load(f)
    except json.JSONDecodeError as e:
        raise Levererades_inte(
            f"{os.path.basename(sokvag)} ar inte komplett JSON ({e}). "
            f"pdal_wrench skriver ibland en avhuggen VPC-fil."
        )
    rutor = d.get("features") or []
    if not rutor:
        raise Levererades_inte(f"{os.path.basename(sokvag)} innehaller inga rutor.")
    return len(rutor)


def kontrollera_punktmoln(sokvag: str, *, minsta_punkter: int = 1) -> int:
    """LAZ/LAS: gar att lasa och innehaller punkter. Returnerar antalet."""
    _finns(sokvag, 512)
    from osgeo import gdal
    gdal.UseExceptions()
    import struct
    with open(sokvag, "rb") as f:
        b = f.read(256)
    if b[:4] != b"LASF":
        raise Levererades_inte(f"{os.path.basename(sokvag)} ar inte en LAS/LAZ-fil.")
    vmaj, vmin = b[24], b[25]
    n = struct.unpack_from("<I", b, 107)[0]
    if (vmaj, vmin) >= (1, 4):
        n14 = struct.unpack_from("<Q", b, 247)[0]
        if n14:
            n = n14
    if n < minsta_punkter:
        raise Levererades_inte(
            f"{os.path.basename(sokvag)} innehaller {n} punkter, vantade minst "
            f"{minsta_punkter}. Ett klassfilter som inte traffade nagot ger detta."
        )
    return n


def kontrollera_projekt(sokvag: str, *, vantad_crs: str = "EPSG:3006",
                        vantade_lager: int | None = None) -> None:
    """QGIS-projekt: CRS satt, sokvagar relativa, alla lager giltiga.

    Ett projekt som byggs programmatiskt arver inte CRS fran forsta lagret. Utan
    kontroll blir felet en karta i skala 1:42 000 000 -- inget felmeddelande.
    """
    from qgis.core import QgsProject
    _finns(sokvag, 512)
    p = QgsProject()
    if not p.read(sokvag):
        raise Levererades_inte(f"{os.path.basename(sokvag)} gar inte att lasa.")
    if p.crs().authid() != vantad_crs:
        raise Levererades_inte(
            f"{os.path.basename(sokvag)} har CRS "
            f"{p.crs().authid() or '(tomt)'}, vantade {vantad_crs}. Ett tomt CRS "
            f"renderar SWEREF-koordinater som grader."
        )
    if vantade_lager is not None and len(p.mapLayers()) != vantade_lager:
        raise Levererades_inte(
            f"{os.path.basename(sokvag)} innehaller {len(p.mapLayers())} lager, "
            f"vantade {vantade_lager}. Ett lager som tyst hoppats over upptacks "
            f"annars forst i falt.")
    trasiga = [l.name() for l in p.mapLayers().values() if not l.isValid()]
    if trasiga:
        raise Levererades_inte(
            f"{os.path.basename(sokvag)}: ogiltiga lager -- {', '.join(trasiga)}"
        )
    with open(sokvag, encoding="utf-8") as f:
        xml = f.read()
    # Forsta versionen letade efter "<absolute>true</absolute>". QGIS skriver
    # `<Absolute type="bool">false</Absolute>`, sa kontrollen kunde aldrig slaa
    # till -- den sag ut att gora sitt jobb och gjorde ingenting. Och flaggan
    # racker anda inte: den styr bara vad QGIS sjalv relativiserar.
    # ProjectGpsSettings skrivs ordagrant och slapper igenom en absolut sokvag
    # med flaggan korrekt satt. Leta darfor efter sokvagarna, inte efter
    # flaggan.
    if re.search(r'<Absolute type="bool">\s*true\s*</Absolute>', xml):
        raise Levererades_inte(
            f"{os.path.basename(sokvag)} ar sparat med absoluta sokvagar. Alla "
            f"lager blir roda pa faltdatorn."
        )
    funna = _absoluta_sokvagar(xml)
    if funna:
        raise Levererades_inte(
            f"{os.path.basename(sokvag)} innehaller absoluta sokvagar:\n   "
            + "\n   ".join(funna[:5])
            + "\nDe pekar pa den har datorn och foljer inte med till faltdatorn."
        )


# En enhetsbeteckning foljd av separator, eller en UNC-sokvag, eller file://.
# Enheten ar ett ensamt tecken -- utan den avgransningen fastnar slutet av varje
# URI-schema i uttrycket.
_ABSOLUT = re.compile(
    r"(?<![A-Za-z])(?:[A-Za-z]:[\\/]|\\\\[A-Za-z0-9_.-]+\\)[^\"'<>|*?\n]*"
    r"|file://[^\"'<>|\n]*")

# Sokvagar som inte hor till projektmappen men anda ar giltiga att lamna kvar.
_UNDANTAG = ("qgis://", "memory://", "base64:")


def _absoluta_sokvagar(xml: str) -> list[str]:
    ut: list[str] = []
    for traff in _ABSOLUT.finditer(xml):
        text = traff.group(0).strip()
        if any(text.startswith(u) for u in _UNDANTAG) or text in ut:
            continue
        ut.append(text)
    return ut


def halvfardig(mal: str) -> str:
    """Namn pa den halvfardiga filen: `stam.delvis.ext`, inte `stam.ext.delvis`.

    Atomiciteten i avsnitt 8 kraver att filen heter nagot annat tills den ar
    komplett. Den naiva varianten -- lagga `.delvis` sist -- forstor filandelsen,
    och bade PDAL och GDAL valjer skrivare pa just den. Det slog till tva ganger:
    GDAL med *Cannot guess driver*, PDAL med *Cannot determine writer for output
    file*. GDAL gick att radda med ett uttryckligt `format="GTiff"`; PDAL
    translate har ingen motsvarande flagga som gar att satta lika enkelt.

    Att i stallet lagga `.delvis` **fore** andelsen loser bada pa en gang och
    kraver ingen kannedom om vilket format anropet rakar skriva. `.copc.laz`
    blir `.copc.delvis.laz` -- fortfarande LAZ for den som laser andelsen, och
    fortfarande ett namn som inte gar att forvaxla med den fardiga filen.

    Ingenting i pluginet soker filer med jokertecken, sa en `.delvis.laz` i en
    arbetskatalog kan inte plockas upp av misstag.
    """
    stam, ext = os.path.splitext(mal)
    return f"{stam}{_min_markering()}{ext}" if ext else mal + _min_markering()


def stada_gamla_delvis(mal: str, aldre_an_timmar: float = 24.0) -> int:
    """Ta bort OVERGIVNA halvfardiga filer for samma mal. Returnerar antalet.

    Sedan mellanledet fick dator och process i namnet kan en korning som dog
    -- stromavbrott, kraschat QGIS -- lamna efter sig en halvfardig fil som
    ingen nagonsin skriver over. I ett gemensamt arkiv pa en NAS ar det
    gigabyte som ligger och skrapar i all evighet.

    Darfor sopas de bort har. **Bara gamla**: en fil som rors just nu hor till
    en kollega som haller pa, och den far vara i fred. Ett dygn ar med god
    marginal -- den langsta uppmatta nedladdningen av en distributionsruta ar
    minuter, inte timmar.
    """
    import glob
    stam, ext = os.path.splitext(mal)
    granslinje = time.time() - aldre_an_timmar * 3600
    n = 0
    for f in glob.glob(f"{glob.escape(stam)}.delvis.*{ext}"):
        try:
            if os.path.getmtime(f) < granslinje:
                os.remove(f)
                n += 1
        except OSError:
            pass
    return n


def _min_markering() -> str:
    """`.delvis` plus vem som skriver -- dator och process.

    **Arkivet ar gemensamt.** Det ar hela poangen med det: alla pekar pa samma
    katalog pa en NAS och fyller pa den tillsammans. Men mellanledet hette
    bara `.delvis`, likadant for alla, och nedladdningen borjar med att ta bort
    ett mellanled som redan finns. Tva kollegor som hamtade samma ruta inom
    samma minuter raderade alltsa varandras halvfardiga fil och skrev till
    samma namn.

    Punktantalet kontrolleras mot katalogen innan filen far sitt riktiga namn,
    sa arkivet blev sannolikt inte trasigt -- men den ene fick ett obegripligt
    "filen ar sannolikt ofullstandig" i stallet for det verkliga skalet.

    Med dator och process i namnet kan de tva inte mota varandra. Den som blir
    fardig forst ger filen dess riktiga namn; den andre skriver over den med
    samma innehall, vilket ar ofarligt.
    """
    import socket
    dator = "".join(t for t in socket.gethostname() if t.isalnum() or t in "-_")
    return f".delvis.{dator[:24] or 'okand'}-{os.getpid()}"


def pluginversion() -> str:
    """Versionen ur metadata.txt. Tom strang om raden inte gar att lasa."""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "metadata.txt")
    try:
        with open(p, encoding="utf-8") as f:
            for rad in f:
                if rad.startswith("version="):
                    return rad.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def _rensa_vid_versionsbyte(mapp: str) -> bool:
    """Toom arbetskatalogen om den gjordes av en annan version. True om tommd.

    Markningen skrivs forst nar katalogen ar tom, sa ett avbrott mitt i
    tomningen lamnar en omarkt katalog -- som tomms igen nasta gang. Det ar
    ratt fel att gora: att stada for mycket kostar tid, att stada for lite
    kostar en tyst felaktig hojdmodell.
    """
    import shutil
    ver = pluginversion()
    if not ver:
        return False
    stampel = os.path.join(mapp, "_version.txt")
    try:
        with open(stampel, encoding="utf-8") as f:
            if f.read().strip() == ver:
                return False
    except OSError:
        pass                                    # saknas eller oläsbar
    tommd = False
    for namn in os.listdir(mapp):
        if namn == "_version.txt":
            continue
        bana = os.path.join(mapp, namn)
        try:
            shutil.rmtree(bana) if os.path.isdir(bana) else os.remove(bana)
            tommd = True
        except OSError:
            # Lasta filer far sta kvar. Markningen skrivs da INTE, sa nasta
            # korning forsoker igen i stallet for att tro att allt ar rent.
            return tommd
    try:
        with open(stampel, "w", encoding="utf-8") as f:
            f.write(ver + "\n")
    except OSError:
        pass
    return tommd


def arbetsplats(namn: str) -> str:
    r"""En ASCII-sokvag att lata pdal_wrench arbeta i.

    **Varfor detta behovs, och varfor bara har.** Uppmatt 2026-09-11 mot en
    sokvag med a-ring och prickar:

      * GDAL laser och skriver utan problem
      * `pdal translate` skriver LAZ utan problem
      * `pdal:virtualpointcloud` skapar **ingen fil** och rapporterar framgang
      * `pdal_wrench to_raster_tin` returnerar **kod 0** och skriver ingen fil,
        med *Failed to read input VPC file* pa stdout

    Alltsa: det ar pdal_wrench, inte formaten och inte GDAL. Och den ljuger --
    nollan i returkoden ar varfor `kontrollera_raster` maste finnas.

    Slutsatsen ar att begransningen inte behover na anvandaren. Den galler bara
    arbetsfilerna, sa de laggs har medan leveransen gar dit anvandaren vill --
    uppdragskatalogen far heta *Naldsjon O 2026:14* med prickar och allt,
    eftersom bara GDAL ror den.

    Ligger inte ens systemets temp-katalog i ASCII (en anvandare som heter Asa
    med a-ring racker) tas `C:\lm_faltunderlag_arbete` i stallet.

    **Katalogen ar VERSIONSMARKT, och tomms nar markningen inte stammer.**
    Mellanleden ligger kvar mellan korningar och aterbrukas -- de ar stora och
    dyra att gora om. Men ett mellanled fran en ANNAN version bar den
    versionens fel, och det galler oavsett om felet ar kant.

    Skalet ar konkret. I 0.9.56 rattades en tyst punktforlust i beskarningen
    (se punktmoln.filtrera_mark): 0.9.46-0.9.55 kunde leverera en brakdel av
    markpunkterna utan att nagot klagade. Ett klassfiltrerat mellanled som
    gjordes av de versionerna ar tyst fel, och aterbrukas det av 0.9.56 far
    anvandaren tillbaka exakt det fel som nyss rattades -- och det ser ut som
    att rattningen inte bet.

    Darfor `_version.txt`. Star det nagot annat an pluginets version dar
    slangs innehallet, och steget gors om mot ratt kod. En omarkt katalog
    raknas som fel version: den gjordes av en utgava fore 0.9.57.
    """
    import tempfile
    stam = "".join(t if (t.isalnum() or t in "-_") else "_" for t in
                   unicodedata.normalize("NFKD", namn)
                   .encode("ascii", "ignore").decode()) or "uppdrag"
    for rot in (tempfile.gettempdir(),
                os.path.join(os.environ.get("SystemDrive", "C:") + os.sep,
                             "lm_faltunderlag_arbete")):
        if any(ord(t) > 127 for t in rot):
            continue
        mal = os.path.join(rot, "lm_faltunderlag", stam)
        try:
            os.makedirs(mal, exist_ok=True)
            _rensa_vid_versionsbyte(mal)
            return mal
        except OSError:
            continue
    raise Levererades_inte(
        "Hittade ingen skrivbar arbetskatalog utan å, ä eller ö. pdal_wrench "
        "kan inte arbeta i en sådan sökväg — den skriver ingen fil och "
        "rapporterar ändå framgång. Sätt TEMP till en sökväg med bara a–z."
    )


def utan_fonster() -> dict:
    """Flaggor som halller kommandotolken dold nar pdal kors.

    Varje `subprocess`-anrop oppnar annars ett svart konsolfonster som blinkar
    forbi mitt over QGIS. Det ar inget anvandaren behover se -- all utdata
    fangas och visas i forloppsrutan anda -- och under ett uttag blir det manga.

    `CREATE_NO_WINDOW` finns bara pa Windows; pa andra plattformar ar dicten tom
    och anropet ser likadant ut.
    """
    import subprocess
    flagga = getattr(subprocess, "CREATE_NO_WINDOW", None)
    return {"creationflags": flagga} if flagga is not None else {}


URSPRUNGSNYCKEL = "LM_FALTUNDERLAG_URSPRUNG"


def satt_ursprung(sokvag: str, text: str) -> None:
    """Skriv in VARIFRAN hojdmodellen kommer i filen sjalv.

    Skalet ar en verklig lucka. En modell som verktyget byggt kan matas tillbaka
    in i ett senare uppdrag -- det ar hela poangen med "Anvand befintlig
    hojdmodell", och det ar vad man gor nar rastreringen redan kostat en timme.
    Men da hoppas lassteget over, och med det forsvann kampanjbeteckning,
    flygdatum och punkttathet ur uttag.txt. Provat 2026-09-16: ett uttag byggt
    pa 25F011 fran 2025 sa bara "framstalld utanfor verktyget".

    Uppgiften hor darfor hemma i FILEN, inte i kedjans minne: den overlever att
    filen kopieras, byter namn och anvands om ett halvar. Saknas taggen ar
    modellen gjord nagon annanstans, och da ska verktyget saga just det i
    stallet for att gissa fram en kampanj ur omradets koordinater.
    """
    if not text:
        return
    from osgeo import gdal
    gdal.UseExceptions()
    ds = gdal.Open(sokvag.split("|")[0], gdal.GA_Update)
    if ds is None:
        return
    ds.SetMetadataItem(URSPRUNGSNYCKEL, text)
    ds = None


def kontrollera_dem(sokvag: str, vantat_crs: str, yta=None) -> dict:
    """Granska en hojdmodell som kommer utifran. Returnerar fakta om den.

    En modell som verktyget sjalv framstallt ar kand: 0,5 m, float32, SWEREF 99
    TM, exakt den buffrade ytan. En som kommer fran Quick Terrain Modeler, fran
    bestallaren eller fran ett tidigare uppdrag kan vara vad som helst, och
    varje avvikelse ger en tyst felaktighet langre fram:

    * **Fel koordinatsystem** lagger skuggbilden nagon annanstans an omradet.
      Verktyget transformerar inte -- att omprojicera en hojdmodell forandrar
      hojdvardena genom interpolation, och det ska inte ske i tysthet.
    * **Flera band** betyder att det inte ar en hojdmodell utan nagot annat, en
      RGB-bild till exempel.
    * **Heltal** betyder decimeter eller meter som enhet, och da blir
      skuggbilderna trappstegsformiga. Tillats, men ar vart en anmarkning.
    * **Tacker inte ytan** ger skuggbilder med hal dar arbetsomradet ar. Det
      syns forst nar nagon zoomar dit i falt.

    `yta` ar en QgsGeometry i samma CRS. Utelamnas den gors ingen
    tackningskontroll.
    """
    from osgeo import gdal
    gdal.UseExceptions()
    if not os.path.exists(sokvag.split("|")[0]):
        raise Levererades_inte(f"Höjdmodellen finns inte: {sokvag}")
    ds = gdal.Open(sokvag.split("|")[0])
    if ds is None:
        raise Levererades_inte(f"Höjdmodellen gick inte att öppna: {sokvag}")

    # Jamfor den HORISONTELLA delen. Verktygets egen hojdmodell arver EPSG:5845
    # fran punktmolnet -- "SWEREF99 TM + RH2000 height" -- som ar 3006 i planet
    # med ett hojdsystem pahangt. En strikt jamforelse mot 3006 avvisar alltsa
    # verktygets eget utdata, vilket den forsta versionen av kontrollen gjorde.
    # Att hojdsystemet ar angivet ar dessutom battre, inte samre.
    from qgis.core import QgsCoordinateReferenceSystem
    sr = ds.GetSpatialRef()
    kod = f"EPSG:{sr.GetAuthorityCode(None)}" if sr is not None else ""

    def _plan(c: str) -> str:
        k = QgsCoordinateReferenceSystem(c)
        h = k.horizontalCrs() if hasattr(k, "horizontalCrs") else k
        return (h.authid() or k.authid()).upper()

    if not kod or _plan(kod) != _plan(vantat_crs):
        raise Levererades_inte(
            f"Höjdmodellen ligger i {kod or 'okänt koordinatsystem'}, inte "
            f"{vantat_crs}.\n\n"
            f"Verktyget projicerar inte om den. En omprojicering interpolerar "
            f"höjdvärdena, och det ska inte ske i tysthet i ett underlag som "
            f"ska mätas i. Projicera om den själv först, eller framställ den i "
            f"{vantat_crs} från början.")

    if ds.RasterCount != 1:
        raise Levererades_inte(
            f"Höjdmodellen har {ds.RasterCount} band. En höjdmodell har ett.")

    gt = ds.GetGeoTransform()
    upp = abs(gt[1])
    typ = gdal.GetDataTypeName(ds.GetRasterBand(1).DataType)
    fakta = {
        "upplosning_m": upp,
        "datatyp": typ,
        "bredd": ds.RasterXSize,
        "hojd": ds.RasterYSize,
        "utbredning": (gt[0], gt[3] + gt[5] * ds.RasterYSize,
                       gt[0] + gt[1] * ds.RasterXSize, gt[3]),
        # Ursprunget, om modellen bar det. Se satt_ursprung nedan.
        "ursprung": (ds.GetMetadataItem(URSPRUNGSNYCKEL) or ""),
        "anmarkningar": [],
    }
    if not typ.startswith("Float"):
        fakta["anmarkningar"].append(
            f"Höjdvärdena är {typ}, inte flyttal. Skuggbilderna kan bli "
            f"trappstegsformade om enheten är decimeter eller meter.")
    if abs(abs(gt[5]) - upp) > 1e-6:
        fakta["anmarkningar"].append(
            f"Cellerna är inte kvadratiska: {upp:g} × {abs(gt[5]):g} m.")

    if yta is not None:
        from qgis.core import QgsGeometry, QgsRectangle
        x0, y0, x1, y1 = fakta["utbredning"]
        tack = QgsGeometry.fromRect(QgsRectangle(x0, y0, x1, y1))
        if not tack.contains(yta):
            saknas = yta.difference(tack)
            andel = (saknas.area() / yta.area()) if yta.area() else 0
            if andel > 0.001:
                raise Levererades_inte(
                    f"Höjdmodellen täcker inte hela arbetsområdet — "
                    f"{andel:.0%} ligger utanför.\n\n"
                    f"Modellens utbredning: {x0:.0f} {y0:.0f} – {x1:.0f} {y1:.0f}\n"
                    f"Skuggbilderna skulle få hål just där området är, och det "
                    f"upptäcks först i fält.")
    ds = None
    return fakta
