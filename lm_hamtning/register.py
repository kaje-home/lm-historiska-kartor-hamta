"""Registret -- kontraktet mellan Gallra, Rektifiera, Tipspunkt och Export.

Ett GeoPackage i arkivet (avsnitt 10). Schemat bestams innan nagot annat
byggs; andras det, hojs `SCHEMAVERSION` och `_uppgradera` far en rad.

Beslut 2026-09-28: lokalt nu, delbart sen
-----------------------------------------
Avsnitt 14 lamnade oppet om arkivet ska delas mellan flera anvandare.
Anvandaren valde: ett register per anvandare nu, men schemat forbereds for
att flera register ska kunna slas ihop senare utan omnumrering. Det betyder:

* **Varje rad har en global identitet.** Akter och sidor har naturliga
  nycklar som ar desamma for alla (`REG:lm23:000462nb`, sidans GUID ur
  arkivet). Allt annat -- beslut, filer, rektifieringar, passpunkter, tips,
  exporter -- far ett UUID. Referenser mellan tabeller gar via dessa, aldrig
  via `fid`. `fid` finns for att QGIS och GDAL vill ha en heltalsnyckel; den
  ar lokal och far skilja sig mellan tva register.
* **Vem och nar** pa allt som en manniska gor: beslut, tips, rektifieringar,
  exporter.
* **Beslut skrivs, andras aldrig.** Ett nytt beslut ar en ny rad; det senaste
  galler. Tva register slas ihop genom att raderna laggs ihop.
* **Ingen lasningslogik**, och rollback-journal (SQLites forval), inte WAL:
  en fil, inga sidofiler, sa att registret gar att flytta och kopiera.

Hur filen byggs
---------------
GDAL skapar ett tomt GeoPackage (huvud, obligatoriska tabeller). Tabellerna
skapas sedan med SQL, sa att nycklar, referenser och CHECK-villkor kommer
med -- det gar inte genom OGR:s lagerskapande. De registreras i
`gpkg_contents` sa att QGIS ser dem.

`ADD_GPKG_OGR_CONTENTS=NO`: GDAL:s raknare av antal objekt uppdateras bara
nar GDAL sjalv skriver. Vi skriver med sqlite3, och en inaktuell raknare
far QGIS att visa fel antal.

Tipspunkterna far ingen rumslig index. En R-trad i GeoPackage underhalls av
utlosare som anropar GDAL:s SQL-funktioner, och da gar tabellen inte att
skriva med sqlite3. Tipsen ar fa; QGIS klarar dem utan index.
"""
from __future__ import annotations

import getpass
import json
import os
import sqlite3
import struct
import uuid as _uuid
from datetime import datetime, timezone

SCHEMAVERSION = 2
CRS_EPSG = 3006         # SWEREF 99 TM

BESLUT = ("behall", "kasta", "osaker")

_TABELLER = """
CREATE TABLE egenskap (
    fid             INTEGER PRIMARY KEY AUTOINCREMENT,
    namn            TEXT NOT NULL UNIQUE,
    varde           TEXT
);

-- En akt ur nagot av arkiven. Skrivs forst ur sokningen, fylls pa ur
-- metadatat. `nyckel` = arkiv:bas:ktun, samma for alla anvandare.
CREATE TABLE akt (
    fid             INTEGER PRIMARY KEY AUTOINCREMENT,
    nyckel          TEXT NOT NULL UNIQUE,
    arkiv           TEXT NOT NULL CHECK (arkiv IN ('REG', 'LMS')),
    bas             TEXT NOT NULL,
    ktun            TEXT NOT NULL,
    beteckning      TEXT NOT NULL,
    atgard          TEXT,           -- "Storskifte"; flera skiljs med "; "
    atgardskod      TEXT,           -- "SS"
    ar              INTEGER,
    datum           TEXT,           -- ISO, bara nar dagen ar kand
    period          TEXT,           -- LMS "1762-71"
    lan             TEXT,
    socken          TEXT,
    trakter         TEXT,           -- JSON-lista; REG: ursprungligt namn
    gallande_trakter TEXT,          -- JSON-lista; REG GTRA
    byar            TEXT,           -- JSON [{namn, socken}]; LMS RBY
    fastighetsnummer TEXT,          -- JSON-lista; REG FNR, bara for matchning
    antal_sidor     INTEGER,
    antal_kartsidor INTEGER,        -- NULL = sidregistret ar inte hamtat
    har_karta       INTEGER,        -- REG-sokningens kart-flagga; NULL = okant
    anmarkning      TEXT,
    ra_sok          TEXT,           -- JSON, sokningens post
    ra_metadata     TEXT,           -- JSON, metadatats post
    sokt            TEXT,           -- nar sokposten senast skrevs
    hamtad          TEXT            -- nar metadatat hamtades; NULL = aldrig
);
CREATE INDEX akt_socken ON akt (socken);

CREATE TABLE sida (
    fid             INTEGER PRIMARY KEY AUTOINCREMENT,
    guid            TEXT NOT NULL UNIQUE,   -- AIP ur arkivet
    akt             TEXT NOT NULL REFERENCES akt (nyckel),
    lopnr           INTEGER NOT NULL,       -- visarens sidnummer
    handling        INTEGER,
    sidn            INTEGER,
    sidtyp          TEXT NOT NULL,          -- KARTA-F, AKT, LMS_KARTA ...
    karta           INTEGER NOT NULL CHECK (karta IN (0, 1)),
    djvu            TEXT,
    tiff            TEXT,
    bredd_px        INTEGER,
    hojd_px         INTEGER,
    storlek_byte    INTEGER,
    UNIQUE (akt, lopnr)
);

-- Beslut andras aldrig; det senaste per akt (och sida) galler.
CREATE TABLE beslut (
    fid             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT NOT NULL UNIQUE,
    akt             TEXT NOT NULL REFERENCES akt (nyckel),
    sida            TEXT REFERENCES sida (guid),    -- NULL = hela akten
    beslut          TEXT NOT NULL CHECK (beslut IN ('behall', 'kasta', 'osaker')),
    kommentar       TEXT,
    tid             TEXT NOT NULL,
    anvandare       TEXT NOT NULL
);
CREATE INDEX beslut_akt ON beslut (akt, tid);

-- Originalet, sa som det hamtades. Sokvagen ar relativ arkivet.
CREATE TABLE fil (
    fid             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT NOT NULL UNIQUE,
    sida            TEXT NOT NULL REFERENCES sida (guid),
    sokvag          TEXT NOT NULL UNIQUE,
    format          TEXT NOT NULL,          -- "GTiff/ZSTD", se arkivfil.py
    storlek_byte    INTEGER,
    sha256          TEXT,
    bredd_px        INTEGER,
    hojd_px         INTEGER,
    hamtad          TEXT NOT NULL,
    anvandare       TEXT NOT NULL
);

-- En rektifiering ar en VRT ovanpa originalet. Lagesosakerheten raknas
-- lamna-en-utanfor mot ett polynom, aven nar kartan transformeras med TPS.
CREATE TABLE rektifiering (
    fid             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT NOT NULL UNIQUE,
    fil             TEXT NOT NULL REFERENCES fil (uuid),
    points_fil      TEXT,                   -- relativ arkivet
    vrt_fil         TEXT,                   -- relativ arkivet
    crs             TEXT NOT NULL DEFAULT 'EPSG:3006',
    transform       TEXT NOT NULL,          -- polynom1..3, tps, helmert
    antal_passpunkter INTEGER NOT NULL,
    rms_m           REAL,
    loo_medel_m     REAL,
    loo_p95_m       REAL,
    referens        TEXT REFERENCES rektifiering (uuid),  -- kedjan
    osakerhet_m     REAL,                   -- sammanlagd, med kedjans
    aktiv           INTEGER NOT NULL DEFAULT 1 CHECK (aktiv IN (0, 1)),
    kommentar       TEXT,
    tid             TEXT NOT NULL,
    anvandare       TEXT NOT NULL
);

CREATE TABLE passpunkt (
    fid             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT NOT NULL UNIQUE,
    rektifiering    TEXT NOT NULL REFERENCES rektifiering (uuid),
    nr              INTEGER NOT NULL,
    bild_x          REAL NOT NULL,          -- pixel i originalet
    bild_y          REAL NOT NULL,
    karta_x         REAL NOT NULL,          -- i rektifieringens crs
    karta_y         REAL NOT NULL,
    referenstyp     TEXT,                   -- sjostrand, akerhorn, kyrka ...
    referenslager   TEXT,                   -- vilket lager punkten togs mot
    loo_fel_m       REAL,                   -- avvikelse nar punkten lamnas ute
    aktiv           INTEGER NOT NULL DEFAULT 1 CHECK (aktiv IN (0, 1)),
    UNIQUE (rektifiering, nr)
);

-- Positionens historik: en rad per rektifiering tipset flyttats ifran.
CREATE TABLE tipspunkt_historik (
    fid             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT NOT NULL UNIQUE,
    tipspunkt       TEXT NOT NULL REFERENCES tipspunkt (uuid),
    x               REAL NOT NULL,
    y               REAL NOT NULL,
    sokradie_m      REAL,
    rektifiering    TEXT REFERENCES rektifiering (uuid),
    giltig_till     TEXT NOT NULL,
    anvandare       TEXT NOT NULL
);

CREATE TABLE export (
    fid             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT NOT NULL UNIQUE,
    tid             TEXT NOT NULL,
    anvandare       TEXT NOT NULL,
    omrade_wkt      TEXT,                   -- EPSG:3006
    malmapp         TEXT NOT NULL,
    fil             TEXT NOT NULL,
    antal_tips      INTEGER NOT NULL,
    lamningsdatabas TEXT
);
"""

# Jobbet (avsnitt 5b, version 2): arbetet gors omrade for omrade -- indexrutor,
# en kraftledning -- inte socken for socken. Omradet som WKT i SWEREF 99 TM,
# som i `export`. `jobb_akt`: akterna Gallra tog med for jobbet, och hur stor
# del av omradet deras trakter ror (NULL = okant, t.ex. hela socknen).
_JOBB = """
CREATE TABLE jobb (
    fid             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT NOT NULL UNIQUE,
    namn            TEXT NOT NULL,
    omrade_wkt      TEXT NOT NULL,          -- EPSG:3006
    skapad          TEXT NOT NULL,
    anvandare       TEXT NOT NULL
);

CREATE TABLE jobb_akt (
    fid             INTEGER PRIMARY KEY AUTOINCREMENT,
    jobb            TEXT NOT NULL REFERENCES jobb (uuid),
    akt             TEXT NOT NULL REFERENCES akt (nyckel),
    yta_m2          REAL,
    UNIQUE (jobb, akt)
);
"""
_JOBBTABELLER = ("jobb", "jobb_akt")

# Tipspunkten ar det enda rumsliga lagret. Faltnamnen ar avsnitt 8:s.
# `bild_x`/`bild_y` ar tipsets lage i originalet: det ar det som gor att ett
# tips kan fa ny position nar kartan rektifieras om -- utan det finns bara
# den gamla kartkoordinaten att flytta, och den vet inget om den nya
# transformen.
_TIPSPUNKT = f"""
CREATE TABLE tipspunkt (
    fid             INTEGER PRIMARY KEY AUTOINCREMENT,
    geom            POINT,
    uuid            TEXT NOT NULL UNIQUE,
    vad             TEXT NOT NULL,
    forvantad_typ   TEXT,
    kalla           TEXT,           -- "LMS Y22-2:1, Avvittring 1771, blad 2"
    arkiv           TEXT,
    beteckning      TEXT,
    atgard          TEXT,
    ar              INTEGER,
    sida            INTEGER,        -- visarens sidnummer
    sokradie_m      REAL,
    rektifiering_id TEXT REFERENCES rektifiering (uuid),
    bild_x          REAL,
    bild_y          REAL,
    socken          TEXT,
    trakt           TEXT,
    skapad          TEXT NOT NULL,
    skapad_av       TEXT NOT NULL,
    andrad          TEXT,
    andrad_av       TEXT
);
"""

_ATTRIBUTTABELLER = ("egenskap", "akt", "sida", "beslut", "fil",
                     "rektifiering", "passpunkt", "tipspunkt_historik",
                     "export")


class RegisterFel(RuntimeError):
    pass


def nu() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def anvandare() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "okänd"


def nytt_uuid() -> str:
    return str(_uuid.uuid4())


def gpkg_punkt(x: float, y: float, srs_id: int = CRS_EPSG) -> bytes:
    """En punkt som GeoPackage-geometri: huvud + WKB, utan utbredning."""
    return (b"GP" + bytes([0, 0b00000001]) + struct.pack("<i", srs_id)
            + struct.pack("<bIdd", 1, 1, x, y))


def las_gpkg_punkt(blob: bytes) -> tuple[float, float]:
    flaggor = blob[3]
    kuvert = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flaggor >> 1) & 0b111]
    wkb = blob[8 + kuvert:]
    ordning = "<" if wkb[0] == 1 else ">"
    x, y = struct.unpack(ordning + "dd", wkb[5:21])
    return x, y


# =========================================================================
# Skapa och oppna
# =========================================================================

def _skapa_tom_gpkg(sokvag: str) -> None:
    from osgeo import gdal, ogr
    gdal.UseExceptions()
    drv = ogr.GetDriverByName("GPKG")
    ds = drv.CreateDataSource(sokvag, options=["ADD_GPKG_OGR_CONTENTS=NO"])
    if ds is None:
        raise RegisterFel(f"{sokvag} kunde inte skapas")
    ds = None


def _srs_wkt(epsg: int) -> str:
    from osgeo import osr
    s = osr.SpatialReference()
    s.ImportFromEPSG(epsg)
    return s.ExportToWkt()


def skapa(sokvag: str) -> None:
    """Ett nytt, tomt register. Finns filen redan ar det ett fel."""
    if os.path.exists(sokvag):
        raise RegisterFel(f"{sokvag} finns redan")
    os.makedirs(os.path.dirname(os.path.abspath(sokvag)), exist_ok=True)
    _skapa_tom_gpkg(sokvag)
    k = sqlite3.connect(sokvag)
    try:
        with k:
            k.executescript(_TABELLER + _TIPSPUNKT + _JOBB)
            k.execute(
                "INSERT OR IGNORE INTO gpkg_spatial_ref_sys (srs_name, srs_id, "
                "organization, organization_coordsys_id, definition) "
                "VALUES (?, ?, 'EPSG', ?, ?)",
                ("SWEREF99 TM", CRS_EPSG, CRS_EPSG, _srs_wkt(CRS_EPSG)))
            tid = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            for t in _ATTRIBUTTABELLER + _JOBBTABELLER:
                k.execute("INSERT INTO gpkg_contents (table_name, data_type, "
                          "identifier, last_change) VALUES (?, 'attributes', ?, ?)",
                          (t, t, tid))
            k.execute("INSERT INTO gpkg_contents (table_name, data_type, "
                      "identifier, last_change, srs_id) "
                      "VALUES ('tipspunkt', 'features', 'tipspunkt', ?, ?)",
                      (tid, CRS_EPSG))
            k.execute("INSERT INTO gpkg_geometry_columns (table_name, "
                      "column_name, geometry_type_name, srs_id, z, m) "
                      "VALUES ('tipspunkt', 'geom', 'POINT', ?, 0, 0)",
                      (CRS_EPSG,))
            k.executemany("INSERT INTO egenskap (namn, varde) VALUES (?, ?)", [
                ("schemaversion", str(SCHEMAVERSION)),
                ("skapad", nu()),
                ("skapad_av", anvandare()),
            ])
    finally:
        k.close()


class Register:
    """Ett oppet register. Anvand som kontexthanterare.

    Varje skrivande metod ar en egen transaktion: kort, sa att filen inte
    halls last langre an nodvandigt.
    """

    def __init__(self, sokvag: str, skapa_om_saknas: bool = True):
        if not os.path.exists(sokvag):
            if not skapa_om_saknas:
                raise RegisterFel(f"{sokvag} finns inte")
            skapa(sokvag)
        self.sokvag = sokvag
        self.k = sqlite3.connect(sokvag)
        self.k.row_factory = sqlite3.Row
        self.k.execute("PRAGMA foreign_keys = ON")
        v = self.egenskap("schemaversion")
        if v is None:
            self.k.close()
            raise RegisterFel(f"{sokvag} är inget register för Historiska kartor")
        if int(v) > SCHEMAVERSION:
            self.k.close()
            raise RegisterFel(
                f"{sokvag} har schemaversion {v}, men den här versionen av "
                f"pluginet känner bara till {SCHEMAVERSION}. Uppdatera pluginet.")
        if int(v) < SCHEMAVERSION:
            self._uppgradera(int(v))

    def _uppgradera(self, fran: int) -> None:
        """Aldre register far det som tillkommit; inget befintligt andras."""
        tid = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        with self.k:
            if fran < 2:
                self.k.executescript(_JOBB)
                for t in _JOBBTABELLER:
                    self.k.execute("INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, "
                                   "identifier, last_change) VALUES (?, 'attributes', ?, ?)",
                                   (t, t, tid))
            self.k.execute("UPDATE egenskap SET varde = ? WHERE namn = 'schemaversion'",
                           (str(SCHEMAVERSION),))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stang()

    def stang(self) -> None:
        self.k.close()

    def egenskap(self, namn: str) -> str | None:
        try:
            r = self.k.execute("SELECT varde FROM egenskap WHERE namn = ?",
                               (namn,)).fetchone()
        except sqlite3.DatabaseError:
            return None
        return r[0] if r else None

    # ------------------------------------------------------------ akter
    def spara_akter(self, akter) -> None:
        """Skriv akter ur sokning eller metadata. Befintliga uppdateras.

        **Metadata skrivs aldrig over med tomt.** En ny sokning ger poster
        utan sidor och fastigheter; de falten behaller da sina varden. Det
        omvanda -- att metadatat skriver over sokningens -- ar ratt, for
        metadatat vet mer.
        """
        tid = nu()
        with self.k:
            for a in akter:
                har_meta = a.ra_metadata is not None
                self.k.execute("""
                    INSERT INTO akt (nyckel, arkiv, bas, ktun, beteckning,
                        atgard, atgardskod, ar, datum, period, lan, socken,
                        trakter, gallande_trakter, byar, fastighetsnummer,
                        antal_sidor, antal_kartsidor, har_karta, anmarkning,
                        ra_sok, ra_metadata, sokt, hamtad)
                    VALUES (:nyckel, :arkiv, :bas, :ktun, :beteckning,
                        :atgard, :atgardskod, :ar, :datum, :period, :lan,
                        :socken, :trakter, :gallande_trakter, :byar,
                        :fastighetsnummer, :antal_sidor, :antal_kartsidor,
                        :har_karta, :anmarkning, :ra_sok, :ra_metadata,
                        :sokt, :hamtad)
                    ON CONFLICT (nyckel) DO UPDATE SET
                        beteckning = excluded.beteckning,
                        atgard = excluded.atgard,
                        atgardskod = COALESCE(excluded.atgardskod, atgardskod),
                        ar = excluded.ar,
                        datum = COALESCE(excluded.datum, datum),
                        period = COALESCE(excluded.period, period),
                        lan = COALESCE(excluded.lan, lan),
                        socken = COALESCE(excluded.socken, socken),
                        trakter = COALESCE(excluded.trakter, trakter),
                        gallande_trakter = COALESCE(excluded.gallande_trakter,
                                                    gallande_trakter),
                        byar = COALESCE(excluded.byar, byar),
                        fastighetsnummer = COALESCE(excluded.fastighetsnummer,
                                                    fastighetsnummer),
                        antal_sidor = COALESCE(excluded.antal_sidor, antal_sidor),
                        antal_kartsidor = COALESCE(excluded.antal_kartsidor,
                                                   antal_kartsidor),
                        har_karta = COALESCE(excluded.har_karta, har_karta),
                        anmarkning = COALESCE(excluded.anmarkning, anmarkning),
                        ra_sok = COALESCE(excluded.ra_sok, ra_sok),
                        ra_metadata = COALESCE(excluded.ra_metadata, ra_metadata),
                        sokt = COALESCE(excluded.sokt, sokt),
                        hamtad = COALESCE(excluded.hamtad, hamtad)
                    """, _akt_rad(a, tid, har_meta))
                if a.sidor is not None:
                    self._spara_sidor(a)

    def _spara_sidor(self, a) -> None:
        for s in a.sidor:
            self.k.execute("""
                INSERT INTO sida (guid, akt, lopnr, handling, sidn, sidtyp,
                                  karta, djvu, tiff)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (guid) DO UPDATE SET
                    lopnr = excluded.lopnr, handling = excluded.handling,
                    sidn = excluded.sidn, sidtyp = excluded.sidtyp,
                    karta = excluded.karta, djvu = excluded.djvu,
                    tiff = excluded.tiff
                """, (s.guid, a.nyckel, s.lopnr, s.handling, s.sidn, s.sidtyp,
                      int(s.karta), s.djvu, s.tiff))

    def akt(self, nyckel: str) -> sqlite3.Row | None:
        return self.k.execute("SELECT * FROM akt WHERE nyckel = ?",
                              (nyckel,)).fetchone()

    def akter(self, socken: str | None = None) -> list[sqlite3.Row]:
        if socken is None:
            return self.k.execute("SELECT * FROM akt ORDER BY ar, beteckning"
                                  ).fetchall()
        return self.k.execute("SELECT * FROM akt WHERE socken = ? COLLATE NOCASE "
                              "ORDER BY ar, beteckning", (socken,)).fetchall()

    def sidor(self, akt: str) -> list[sqlite3.Row]:
        return self.k.execute("SELECT * FROM sida WHERE akt = ? ORDER BY lopnr",
                              (akt,)).fetchall()

    def utan_metadata(self, socken: str | None = None) -> list[str]:
        """Akter vars sidregister inte ar hamtat. REG-akter med `kart=N`
        raknas inte: de har ingen karta att visa (gallringens forsta lager)."""
        sql = ("SELECT nyckel FROM akt WHERE hamtad IS NULL "
               "AND COALESCE(har_karta, 1) = 1")
        arg: tuple = ()
        if socken is not None:
            sql += " AND socken = ? COLLATE NOCASE"
            arg = (socken,)
        return [r[0] for r in self.k.execute(sql + " ORDER BY ar", arg)]

    # ----------------------------------------------------------- beslut
    def satt_beslut(self, akt: str, beslut: str, sida: str | None = None,
                    kommentar: str = "", av: str | None = None) -> str:
        if beslut not in BESLUT:
            raise ValueError(f"okänt beslut {beslut!r}; ett av {BESLUT}")
        u = nytt_uuid()
        with self.k:
            self.k.execute(
                "INSERT INTO beslut (uuid, akt, sida, beslut, kommentar, tid, "
                "anvandare) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (u, akt, sida, beslut, kommentar or None, nu(), av or anvandare()))
        return u

    def gallande_beslut(self, akt: str, sida: str | None = None) -> str | None:
        """Det senaste beslutet for akten (eller sidan). None = inget."""
        r = self.k.execute(
            "SELECT beslut FROM beslut WHERE akt = ? AND sida IS ? "
            "ORDER BY tid DESC, fid DESC LIMIT 1", (akt, sida)).fetchone()
        return r[0] if r else None

    def behallna_akter(self) -> list[sqlite3.Row]:
        """Akter vars senaste beslut ar `behall`."""
        return self.k.execute("""
            SELECT a.* FROM akt a JOIN beslut b ON b.akt = a.nyckel
            WHERE b.sida IS NULL AND b.fid = (
                SELECT fid FROM beslut WHERE akt = a.nyckel AND sida IS NULL
                ORDER BY tid DESC, fid DESC LIMIT 1)
              AND b.beslut = 'behall'
            ORDER BY a.socken, a.ar, a.beteckning""").fetchall()

    def kartsidor_utan_fil(self, akt: str) -> list[sqlite3.Row]:
        """Kartsidor som inte är hämtade och inte kastade var för sig (ett blad
        i en akt med flera kan kastas, användaren 2026-10-01)."""
        return self.k.execute("""
            SELECT s.* FROM sida s WHERE s.akt = ? AND s.karta = 1
              AND NOT EXISTS (SELECT 1 FROM fil f WHERE f.sida = s.guid)
              AND COALESCE((SELECT b.beslut FROM beslut b WHERE b.akt = s.akt
                            AND b.sida = s.guid ORDER BY b.tid DESC, b.fid DESC
                            LIMIT 1), '') != 'kasta'
            ORDER BY s.lopnr""", (akt,)).fetchall()

    def filer(self, akt: str | None = None) -> list[sqlite3.Row]:
        sql = ("SELECT f.*, s.akt, s.lopnr FROM fil f JOIN sida s ON s.guid = f.sida")
        if akt is None:
            return self.k.execute(sql + " ORDER BY f.sokvag").fetchall()
        return self.k.execute(sql + " WHERE s.akt = ? ORDER BY s.lopnr", (akt,)).fetchall()

    def spara_fil(self, sida: str, sokvag: str, format: str, storlek_byte: int,
                  sha256: str, bredd_px: int, hojd_px: int,
                  av: str | None = None) -> str:
        """Ett lagrat original. `sokvag` ar relativ arkivet."""
        u = nytt_uuid()
        with self.k:
            self.k.execute(
                "INSERT INTO fil (uuid, sida, sokvag, format, storlek_byte, sha256, "
                "bredd_px, hojd_px, hamtad, anvandare) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (u, sida, sokvag.replace("\\", "/"), format, storlek_byte, sha256,
                 bredd_px, hojd_px, nu(), av or anvandare()))
        return u

    def ta_bort_fil(self, uuid: str) -> None:
        """Ett lagrat original ur registret -- bara om ingen rektifiering pekar
        på det (Ångra sammanfogning, 2026-10-13). Filen själv rörs inte här."""
        n = self.k.execute("SELECT COUNT(*) FROM rektifiering WHERE fil = ?", (uuid,)).fetchone()[0]
        if n:
            raise ValueError("kartan är rektifierad; ta bort rektifieringen först")
        with self.k:
            self.k.execute("DELETE FROM fil WHERE uuid = ?", (uuid,))

    # ------------------------------------------------------ rektifiering
    def kartfiler(self) -> list[sqlite3.Row]:
        """Arbetslistan: varje nedladdad kartsida med sin aktiva rektifiering."""
        return self.k.execute("""
            SELECT f.uuid AS fil, f.sokvag, f.bredd_px, f.hojd_px, s.lopnr, s.guid AS sida,
                   a.nyckel AS akt, a.arkiv, a.beteckning, a.atgard, a.ar,
                   a.socken, a.trakter, a.gallande_trakter,
                   r.uuid AS rektifiering, r.transform, r.antal_passpunkter,
                   r.loo_medel_m, r.loo_p95_m, r.osakerhet_m, r.vrt_fil, r.tid
            FROM fil f JOIN sida s ON s.guid = f.sida JOIN akt a ON a.nyckel = s.akt
            LEFT JOIN rektifiering r ON r.fil = f.uuid AND r.aktiv = 1
            ORDER BY a.socken, a.ar DESC, a.beteckning, s.lopnr, f.sokvag""").fetchall()

    def rektifiering(self, uuid: str) -> sqlite3.Row | None:
        return self.k.execute("SELECT * FROM rektifiering WHERE uuid = ?",
                              (uuid,)).fetchone()

    def passpunkter(self, rektifiering: str) -> list[sqlite3.Row]:
        return self.k.execute("SELECT * FROM passpunkt WHERE rektifiering = ? "
                              "ORDER BY nr", (rektifiering,)).fetchall()

    def spara_rektifiering(self, fil: str, transform: str, bedomning, punkter,
                           points_fil: str | None, vrt_fil: str | None,
                           referens: str | None = None,
                           osakerhet_m: float | None = None, kommentar: str = "",
                           av: str | None = None) -> str:
        """En ny rektifiering av `fil`; den forra blir inaktiv men finns kvar.
        Sokvagarna ar relativa arkivet. `punkter` ar rektifiering.Passpunkt."""
        u = nytt_uuid()
        with self.k:
            self.k.execute("UPDATE rektifiering SET aktiv = 0 WHERE fil = ?", (fil,))
            self.k.execute("""
                INSERT INTO rektifiering (uuid, fil, points_fil, vrt_fil, transform,
                    antal_passpunkter, rms_m, loo_medel_m, loo_p95_m, referens,
                    osakerhet_m, aktiv, kommentar, tid, anvandare)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (u, fil, points_fil, vrt_fil, transform, bedomning.antal,
                 bedomning.rms_m, bedomning.loo_medel_m, bedomning.loo_p95_m,
                 referens, osakerhet_m, kommentar or None, nu(), av or anvandare()))
            self.k.executemany("""
                INSERT INTO passpunkt (uuid, rektifiering, nr, bild_x, bild_y,
                    karta_x, karta_y, referenstyp, referenslager, loo_fel_m, aktiv)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(nytt_uuid(), u, p.nr, p.bild_x, p.bild_y, p.karta_x, p.karta_y,
                  p.referenstyp or None, getattr(p, "referenslager", "") or None,
                  p.loo_fel_m, int(p.aktiv)) for p in punkter])
        return u

    # ------------------------------------------------------------- jobb
    def spara_jobb(self, namn: str, omrade_wkt: str, akter: dict[str, float | None],
                   uuid: str | None = None, av: str | None = None) -> str:
        """Ett jobb (avsnitt 5b) och dess akter {nyckel: berord yta i m2}.
        Finns jobbet (`uuid`, annars samma namn) laggs akterna till och
        omradet laggs ihop med det gamla -- en ledning gallras i omgangar (det
        nya omradet ersatte forst det gamla, 2026-10-02). En akts yta skrivs
        over bara med ett kant varde."""
        with self.k:
            if uuid is None:
                r = self.k.execute("SELECT uuid FROM jobb WHERE namn = ?", (namn,)).fetchone()
                uuid = r[0] if r else None
            if uuid is None:
                uuid = nytt_uuid()
                self.k.execute("INSERT INTO jobb (uuid, namn, omrade_wkt, skapad, anvandare) "
                               "VALUES (?, ?, ?, ?, ?)", (uuid, namn, omrade_wkt, nu(),
                                                          av or anvandare()))
            else:
                r = self.k.execute("SELECT omrade_wkt FROM jobb WHERE uuid = ?", (uuid,)).fetchone()
                self.k.execute("UPDATE jobb SET omrade_wkt = ? WHERE uuid = ?",
                               (_slå_ihop(r[0] if r else None, omrade_wkt), uuid))
            self.k.executemany("""
                INSERT INTO jobb_akt (jobb, akt, yta_m2) VALUES (?, ?, ?)
                ON CONFLICT (jobb, akt) DO UPDATE SET yta_m2 = COALESCE(excluded.yta_m2, yta_m2)
                """, [(uuid, a, y) for a, y in akter.items()])
        return uuid

    def jobben(self) -> list[sqlite3.Row]:
        return self.k.execute("SELECT * FROM jobb ORDER BY skapad DESC").fetchall()

    def jobbets_akter(self, jobb: str) -> dict[str, float | None]:
        """{akt: berord yta i m2} for jobbet."""
        return {r[0]: r[1] for r in self.k.execute(
            "SELECT akt, yta_m2 FROM jobb_akt WHERE jobb = ?", (jobb,))}

    def kastade(self) -> set[str]:
        """Akter vars senaste beslut ar `kasta` -- de visas aldrig igen."""
        rader = self.k.execute("""
            SELECT akt, beslut FROM beslut b WHERE sida IS NULL AND fid = (
                SELECT fid FROM beslut WHERE akt = b.akt AND sida IS NULL
                ORDER BY tid DESC, fid DESC LIMIT 1)""").fetchall()
        return {r[0] for r in rader if r[1] == "kasta"}


def _slå_ihop(gammal: str | None, ny: str) -> str:
    """Tva omraden (WKT) som ett; det nya om det gamla saknas eller inte gar att lasa."""
    if not gammal:
        return ny
    from osgeo import ogr
    a, b = ogr.CreateGeometryFromWkt(gammal), ogr.CreateGeometryFromWkt(ny)
    if a is None or b is None:
        return ny
    return a.Union(b).ExportToWkt()


def _json(v) -> str | None:
    return json.dumps(v, ensure_ascii=False) if v else None


def _akt_rad(a, tid: str, har_meta: bool) -> dict:
    return {
        "nyckel": a.nyckel, "arkiv": a.arkiv, "bas": a.bas, "ktun": a.ktun,
        "beteckning": a.beteckning,
        "atgard": "; ".join(a.atgarder) or None,
        "atgardskod": "; ".join(a.atgardskoder) or None,
        "ar": a.ar, "datum": a.datum, "period": a.period or None,
        "lan": a.lan or None, "socken": a.socken or None,
        "trakter": _json(a.trakter),
        "gallande_trakter": _json(a.gallande_trakter),
        "byar": _json([{"namn": b.namn, "socken": b.socken} for b in a.byar]),
        "fastighetsnummer": _json(a.fastighetsnummer),
        "antal_sidor": a.antal_sidor,
        "antal_kartsidor": a.antal_kartsidor,
        "har_karta": None if a.har_karta is None else int(a.har_karta),
        "anmarkning": a.anmarkning or None,
        "ra_sok": _json(a.ra_sok),
        "ra_metadata": _json(a.ra_metadata),
        "sokt": tid if a.ra_sok is not None else None,
        "hamtad": tid if har_meta else None,
    }
