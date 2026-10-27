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
from typing import Callable

from .atkomst import tolka_nekat
from .kontroll import Levererades_inte, halvfardig, stada_gamla_delvis


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
