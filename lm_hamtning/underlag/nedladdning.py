# Kopierad ur LM Fältunderlag (lm_faltunderlag/verktyg/nedladdning.py, commit 374b15d) 2026-10-08:
# pluginet ska gå utan Fältunderlaget (KRAV avsnitt 2). Rättningar görs i båda.
"""En nedladdning, ett stalle.

**Varfor modulen finns.** Fyra steg laddade ned filer over HTTP och alla fyra
hade skrivit samma trettio rader: mellanled med tillfalligt namn, QEventLoop,
felinsamling, `tolka_nekat`, kontroll, namnbyte. Det ar inte fult -- det ar
dyrt, och priset betalades 2026-09-17.

Den dagen fick mellanledet dator och process i namnet, sa att tva kollegor mot
samma NAS-arkiv inte kan radera varandras halvfardiga filer. Foljdandringen --
att sopa bort OVERGIVNA mellanled, som ingen langre skriver over -- lades in i
tva av de fem nedladdarna. Ortofoto, ekonomiska kartan och ortnamn fick den
inte, och ett ortofotoblad ar 100-500 MB. En rattelse som maste goras pa fem
stallen blir gjord pa tva.

Tva saker till foll ut nar de slogs ihop:

  * **Avbrottsvakten finns nu overallt.** Bara laserhamtningen och
    markhojdmodellen hade den. Ett ortofotoblad pa en halv gigabyte gick alltsa
    inte att avbryta medan det hamtades, av precis samma skal som
    laserhamtningen inte gick det fore 0.9.24: QEventLoop fragar ingen.
  * **Samma felmeddelande oavsett produkt.** `tolka_nekat` kanner igen 401 och
    403 och sager vad som ska bestallas pa Geotorget.

`hamta_ekokarta` star utanfor med vilje: den anvander anonym FTP, och Qt:s
FTP-stod ar borttaget i Qt6.
"""
from __future__ import annotations

import os
import time
from typing import Callable

from .atkomst import tolka_nekat


# Ur kontroll.py (2026-11-05): hämtningen för sig tar med nedladdningen men inte kontrollen.
class Levererades_inte(Exception):
    """Ett steg rapporterade framgang men filen ar inte anvandbar."""


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


def _mb(n: float) -> str:
    return f"{n/1e9:.2f} GB" if n >= 1e9 else f"{n/1e6:.0f} MB"


def hamta_fil(url: str, mal: str, authcfg: str, *, produkt: str,
              etikett: str = "", feedback=None,
              kontrollera: Callable[[str], None] | None = None) -> str:
    """Hamta `url` till `mal`. Returnerar `mal`.

    Filen far sitt riktiga namn forst nar den ar komplett OCH godkand --
    `kontrollera` far mellanledets sokvag och ska kasta `Levererades_inte` om
    innehallet inte duger. En felsida sparas lika garna som ett punktmoln.

    `produkt` gar till `tolka_nekat` och avgor vilket besked anvandaren far
    nar servern svarar 401 eller 403: vilken produkt som ska bestallas.

    Kastar `Levererades_inte` vid fel och vid avbrott. Ett avbrott ar inget
    fel, men det far inte se ut som en lyckad hamtning heller -- anroparen far
    skilja dem at pa `feedback.isCanceled()`.
    """
    from qgis.core import QgsFileDownloader
    from qgis.PyQt.QtCore import QUrl, QEventLoop, QTimer

    namn = etikett or os.path.basename(mal)
    os.makedirs(os.path.dirname(mal), exist_ok=True)
    tillfallig = halvfardig(mal)
    if os.path.exists(tillfallig):
        os.remove(tillfallig)
    stada_gamla_delvis(mal)

    fel: list[str] = []
    loop = QEventLoop()
    h = QgsFileDownloader(QUrl(url), tillfallig, authcfg, delayStart=True)

    def framsteg(hamtat, totalt):
        if totalt > 0 and feedback is not None:
            feedback.setProgress(100 * hamtat / totalt)
            feedback.setProgressText(f"{namn}: {_mb(hamtat)} / {_mb(totalt)}")

    h.downloadProgress.connect(framsteg)
    h.downloadError.connect(
        lambda m: fel.extend(m if isinstance(m, list) else [str(m)]))
    h.downloadExited.connect(loop.quit)

    # **Avbrottet maste bevakas HAR, inte bara mellan filerna.** En slinga som
    # provar `isCanceled()` fore varje ny fil racker sa lange filerna ar sma.
    # En distributionsruta ar 2,6 GB och tar minuter, och under den tiden satt
    # anvandaren i en oppen loop som inte lyssnade: avbrytknappen registrerades
    # men hamtningen fortsatte. Provat 2026-09-16: tre tryck pa krysset,
    # ingenting hande pa flera minuter.
    vakt = QTimer()
    vakt.setInterval(250)
    vakt.timeout.connect(
        lambda: (h.cancelDownload(), loop.quit())
        if feedback is not None and feedback.isCanceled() else None)
    vakt.start()
    h.startDownload()
    loop.exec()
    vakt.stop()

    if feedback is not None and feedback.isCanceled():
        if os.path.exists(tillfallig):
            os.remove(tillfallig)
        raise Levererades_inte(f"{namn}: hämtningen avbröts")

    if fel:
        if os.path.exists(tillfallig):
            os.remove(tillfallig)
        text = "; ".join(fel)
        nekat = tolka_nekat(text, produkt)
        if nekat:
            raise nekat
        raise Levererades_inte(f"{namn}: {text}")

    if kontrollera is not None:
        try:
            kontrollera(tillfallig)
        except Exception:
            if os.path.exists(tillfallig):
                os.remove(tillfallig)
            raise
    os.replace(tillfallig, mal)
    return mal


def kontrollera_zip(sokvag: str) -> None:
    """Kastar `Levererades_inte` om zippen inte ar hel. Som `kontrollera` till `hamta_fil`:
    en nedladdning som brots i fortid blir en zip utan innehallsforteckning eller med fel
    kontrollsumma, och den ska inte fa sitt riktiga namn (granskningen 2026-11-05)."""
    import zipfile
    try:
        with zipfile.ZipFile(sokvag) as z:
            trasig = z.testzip()
    except (zipfile.BadZipFile, OSError, EOFError) as e:
        raise Levererades_inte(f"{os.path.basename(sokvag)} är ingen hel zip-fil: {e}") from e
    if trasig:
        raise Levererades_inte(f"{os.path.basename(sokvag)}: {trasig} är trasig i zip-filen")


def packa_upp(zipfil: str, mal: str, slutar: tuple[str, ...] = ()) -> list[str]:
    """Packar upp `zipfil` i `mal`. -> filerna. `slutar`: bara de andelserna (tomt = alla).

    Varje fil skrivs under ett tillfalligt namn och far sitt riktiga forst nar den ar hel.
    `zipfile.extract` skrev direkt till det riktiga namnet, och en uppackning som brots
    (QGIS stangt, disken full) lamnade en halv geopackage som raknades som hamtad och aldrig
    hamtades om (granskningen 2026-11-05). Det tillfalliga namnet slutar pa `.delvis`, inte
    pa filens andelse som `halvfardig`: annars hittas det av `*.gpkg` i mappen.
    Filnamn som pekar ut ur `mal` hoppas over."""
    import shutil
    import threading
    import zipfile
    rot = os.path.abspath(mal)
    ut = []
    with zipfile.ZipFile(zipfil) as z:
        for info in z.infolist():
            if info.is_dir() or (slutar and not info.filename.lower().endswith(slutar)):
                continue
            dest = os.path.abspath(os.path.join(rot, *info.filename.replace("\\", "/").split("/")))
            if os.path.commonpath([rot, dest]) != rot:
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = f"{dest}.{os.getpid()}.{threading.get_ident()}.delvis"
            try:
                with z.open(info) as kalla, open(tmp, "wb") as fh:
                    shutil.copyfileobj(kalla, fh, 1 << 20)
                os.replace(tmp, dest)
            except BaseException:
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise
            ut.append(dest)
    return ut
