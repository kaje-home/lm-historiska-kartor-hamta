# Kopierad ur LM Fältunderlag (lm_faltunderlag/verktyg/atkomst.py, commit 374b15d) 2026-10-08:
# pluginet ska gå utan Fältunderlaget (KRAV avsnitt 2). Rättningar görs i båda.
"""Atkomst till Geotorget -- utan att binda pluginet till en enskild person.

Kravet: verktyget ska fungera for vem som helst pa arbetsplatsen, inte bara for
den som byggde det. Det utesluter tre annars naraliggande losningar:

* **Inte inloggningsuppgifter i koden.** Uppenbart, men vart att skriva ned.
* **Inte ett hardkodat autentiserings-id.** QGIS autentiseringskonfigurationer
  far slumpade sjustallliga id:n (`9bmz79i`) som ar unika for varje
  `qgis-auth.db`. Samma id betyder olika saker -- eller ingenting -- pa nasta
  dator.
* **Inte uppgifter i installningsfilen.** Den ar tankt att kunna delas och
  versionshanteras; se installningar.py.

I stallet valjer varje anvandare sin egen konfiguration en gang. Valet lagras
per QGIS-profil i QSettings -- det ar ett id, inte en hemlighet, och det ar
vardelost pa nagon annans dator. Sjalva uppgifterna ligger kvar i QGIS
krypterade autentiseringsdatabas och passerar aldrig pluginets kod.

Geotorget anvander Basic-autentisering. QGIS `QgsNetworkAccessManager`
tillsammans med ett authcfg-id satter huvudena sjalv, sa proxy- och
brandvaggskonfiguration foljer med pa kopet.
"""
from __future__ import annotations

from qgis.PyQt.QtCore import QSettings

NYCKEL = "lm_historiska_kartor/authcfg"
# Fältunderlagets inställning är bara ett förval när pluginets egen är tom:
# samma Geotorget-konto i samma QGIS-profil. Pluginet kräver inte Fältunderlaget.
NYCKEL_FALTUNDERLAG = "lm_faltunderlag/authcfg"
VANTAD_METOD = "Basic"


class SaknarAtkomst(Exception):
    """Ingen anvandbar autentiseringskonfiguration ar vald."""


def sparat_id() -> str:
    return (QSettings().value(NYCKEL, "", type=str)
            or QSettings().value(NYCKEL_FALTUNDERLAG, "", type=str))


def spara_id(authcfg: str) -> None:
    QSettings().setValue(NYCKEL, authcfg or "")


def konfigurationer() -> dict[str, str]:
    """id -> namn for alla konfigurationer i den har profilen."""
    from qgis.core import QgsApplication
    am = QgsApplication.authManager()
    return {i: c.name() for i, c in am.availableAuthMethodConfigs().items()}


def kontrollera(authcfg: str | None = None) -> str:
    """Ge ett anvandbart authcfg-id, eller ett begripligt fel.

    Felmeddelandet ska racka for att losa problemet utan att fraga nagon --
    den som far det ar troligen inte den som byggde verktyget.
    """
    from qgis.core import QgsApplication
    am = QgsApplication.authManager()

    if am.isDisabled():
        raise SaknarAtkomst(
            "QGIS autentiseringssystem är avstängt.\n"
            f"{am.disabledMessage()}\n\n"
            "Utan det går det inte att lagra Geotorget-uppgifter säkert."
        )

    valt = authcfg or sparat_id()
    tillgangliga = konfigurationer()

    if not valt:
        raise SaknarAtkomst(_hjalp("Ingen autentisering vald.", tillgangliga))
    if valt not in tillgangliga:
        raise SaknarAtkomst(_hjalp(
            f"Autentiseringen \"{valt}\" finns inte i den här QGIS-profilen.\n"
            "Id:n är unika per dator — ett id som fungerar hos en kollega "
            "betyder ingenting här.", tillgangliga))

    kfg = am.availableAuthMethodConfigs()[valt]
    if kfg.method() != VANTAD_METOD:
        raise SaknarAtkomst(
            f"\"{kfg.name()}\" använder {kfg.method()}, men Geotorget kräver "
            f"{VANTAD_METOD}."
        )
    return valt


def _hjalp(inledning: str, tillgangliga: dict[str, str]) -> str:
    rader = [inledning, "",
             "Så här ordnar du det:",
             "  1. Inställningar → Alternativ → Autentisering",
             "  2. Lägg till en konfiguration av typen Basic med ditt eget",
             "     Geotorget-användarnamn och lösenord",
             "  3. Välj den i verktygets autentiseringsruta",
             "",
             "Uppgifterna lagras i QGIS krypterade databas och lämnar aldrig",
             "din dator. Pluginet ser bara vilken konfiguration som valts."]
    if tillgangliga:
        rader += ["", "Konfigurationer som finns i den här profilen:"]
        rader += [f"     {namn}  ({i})" for i, namn in sorted(
            tillgangliga.items(), key=lambda kv: kv[1])]
    else:
        rader += ["", "Den här profilen har inga konfigurationer alls än."]
    return "\n".join(rader)


def forbered(begaran, authcfg: str):
    """Lagg pa autentisering pa en QNetworkRequest.

    Uppgifterna hamtas av QGIS sjalv ur den krypterade databasen -- de passerar
    aldrig genom pluginets kod och gar darfor inte att rakt ut logga eller lacka.
    """
    from qgis.core import QgsApplication
    am = QgsApplication.authManager()
    if not am.updateNetworkRequest(begaran, authcfg):
        raise SaknarAtkomst(
            "Autentiseringen gick inte att lägga på begäran. Är huvudlösenordet "
            "för autentiseringsdatabasen angivet i den här sessionen?"
        )
    return begaran


def tolka_nekat(text: str, produkt: str) -> Exception | None:
    """Oversatt ett nekat HTTP-svar till nagot en kollega kan agera pa.

    **Geotorget svarar 403, inte 401.** Uppgifterna godtas -- servern vet vem du
    ar -- men kontot saknar bestallning pa just den produkten. Nginx svarar da
    `403 Forbidden` utan `WWW-Authenticate`, och ett verktyg som bara letar
    efter 401 sager i stallet nagot om felaktiga losenord och skickar anvandaren
    at helt fel hall.

    Provat 2026-09-10 mot ett konto med ortnamn och ortofoto men utan hojddata:
    `/namnsatt-plats/` och ortofotobladen svarade 206, `/hojd/data/` svarade 403
    for bade `dsm-skoglig-copc` och `dtm-cog`, medan `/hojd/pub/` (miniatyrer och
    info.json) svarade 206. Behorigheten sitter alltsa pa sokvag, inte pa vard.

    Returnerar en fardig `SaknarAtkomst` eller None om svaret inte var nekat.
    """
    l = text.lower()
    if "403" in text or "forbidden" in l:
        return SaknarAtkomst(
            f"Geotorget nekar åtkomst till {produkt} (403 Forbidden).\n\n"
            "Inloggningen fungerar — servern känner igen kontot — men kontot "
            f"har inte {produkt} beställd. Behörigheten ges per produkt på "
            "geotorget.lantmateriet.se, och en beställning kan behöva göras av "
            "den som administrerar organisationens konto.\n\n"
            f"Tekniskt svar: {text}"
        )
    if "401" in text or "unauthorized" in l or "authentication" in l:
        return SaknarAtkomst(
            f"Inloggningen avvisades vid hämtning av {produkt} (401).\n\n"
            "Det är uppgifterna som inte godtas, inte behörigheten. Kontrollera "
            "användarnamn och lösenord i autentiseringskonfigurationen.\n\n"
            f"Tekniskt svar: {text}"
        )
    return None
