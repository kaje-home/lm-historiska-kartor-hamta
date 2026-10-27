"""Kartsidan i arkivet: hamtad TIFF in, komprimerad och kontrollerad TIFF ut.

Beslut 2026-09-28: ZSTD, forlustfritt
-------------------------------------
Tjansten levererar sidan okomprimerad: 23-hag-10 s. 1 ar 6150 x 5812 px RGB,
107 MB. Provat pa den sidan:

    ingen      107 MB     LZW      87 MB     DEFLATE   74 MB
    ZSTD        70 MB     JPEG 90   9 MB (med forlust)

Anvandaren valde ZSTD: samma pixlar, en tredjedel mindre. Pappersbruset i
skanningen ar skalet till att forlustfritt inte vinner mer.

**Pixlarna jamfors efter skrivningen.** Att filen blev skriven sager inget
om att den blev ratt, och ett original som tyst blivit ett annat ar varre an
ett som saknas -- det ar det enda vi har. Samma regel som i Faltunderlagets
gpkg.py: det som ligger pa disk ar det som galler. Kostar ett par sekunder
per sida, mot tio for hamtningen.

`sha256` i registret ar den lagrade filens, inte den hamtades. Det ar den
filen som ska kunna kontrolleras senare.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

SKAPA = ["COMPRESS=ZSTD", "PREDICTOR=2", "TILED=YES", "BIGTIFF=IF_SAFER"]
FORMAT = "GTiff/ZSTD"
_RADER_PER_VARV = 512


class LagringsFel(RuntimeError):
    """Sidan kunde inte lagras, eller det som lagrades ar inte sidan."""


@dataclass
class Lagrad:
    sokvag: str
    format: str
    storlek_byte: int
    sha256: str
    bredd_px: int
    hojd_px: int


def _sha256(sokvag: str) -> str:
    h = hashlib.sha256()
    with open(sokvag, "rb") as f:
        for bit in iter(lambda: f.read(1 << 20), b""):
            h.update(bit)
    return h.hexdigest()


def _har_zstd() -> bool:
    from osgeo import gdal
    lista = gdal.GetDriverByName("GTiff").GetMetadataItem("DMD_CREATIONOPTIONLIST")
    return "ZSTD" in (lista or "")


def _lika_pixlar(a, b) -> str | None:
    """None om bilderna ar pixelidentiska, annars vad som skiljer."""
    import numpy as np
    if (a.RasterXSize, a.RasterYSize, a.RasterCount) != \
            (b.RasterXSize, b.RasterYSize, b.RasterCount):
        return (f"storleken {b.RasterXSize}×{b.RasterYSize}×{b.RasterCount}, "
                f"väntade {a.RasterXSize}×{a.RasterYSize}×{a.RasterCount}")
    for i in range(1, a.RasterCount + 1):
        ba, bb = a.GetRasterBand(i), b.GetRasterBand(i)
        for y in range(0, a.RasterYSize, _RADER_PER_VARV):
            n = min(_RADER_PER_VARV, a.RasterYSize - y)
            if not np.array_equal(ba.ReadAsArray(0, y, a.RasterXSize, n),
                                  bb.ReadAsArray(0, y, a.RasterXSize, n)):
                return f"band {i} skiljer sig från rad {y}"
    return None


def befintlig(sokvag: str) -> Lagrad:
    """Uppgifterna om en redan lagrad sida, for registret."""
    from osgeo import gdal
    gdal.UseExceptions()
    ds = gdal.Open(sokvag)
    komp = (ds.GetMetadata("IMAGE_STRUCTURE") or {}).get("COMPRESSION", "")
    bredd, hojd = ds.RasterXSize, ds.RasterYSize
    ds = None
    return Lagrad(sokvag=sokvag, format=f"GTiff/{komp}" if komp else "GTiff",
                  storlek_byte=os.path.getsize(sokvag), sha256=_sha256(sokvag),
                  bredd_px=bredd, hojd_px=hojd)


def lagra_tiff(hamtad: str, mal: str, ta_bort_hamtad: bool = True) -> Lagrad:
    """Skriv `hamtad` komprimerad till `mal`. Kastar `LagringsFel`.

    `mal` far sitt namn forst nar pixlarna ar kontrollerade. Finns `mal`
    redan ar det ett fel -- ett original skrivs aldrig over.
    """
    from osgeo import gdal
    gdal.UseExceptions()

    if os.path.exists(mal):
        raise LagringsFel(f"{mal} finns redan; ett original skrivs aldrig över.")
    if not _har_zstd():
        raise LagringsFel(
            "GDAL i den här QGIS-installationen saknar ZSTD-komprimering. "
            "Alla officiella QGIS-byggen från 3.40 har den — uppdatera QGIS.")
    os.makedirs(os.path.dirname(os.path.abspath(mal)), exist_ok=True)
    tmp = f"{mal}.{os.getpid()}.delvis.tif"

    try:
        kalla = gdal.Open(hamtad)
    except RuntimeError as e:
        raise LagringsFel(f"{hamtad} går inte att läsa som bild: {e}") from e
    try:
        ut = gdal.Translate(tmp, kalla, format="GTiff", creationOptions=SKAPA)
        if ut is None:
            raise LagringsFel(f"{tmp} kunde inte skrivas")
        ut = None
        skillnad = _lika_pixlar(kalla, gdal.Open(tmp))
        if skillnad:
            raise LagringsFel(f"{mal}: den lagrade sidan är inte den hämtade — "
                              f"{skillnad}")
        bredd, hojd = kalla.RasterXSize, kalla.RasterYSize
        kalla = None
        os.replace(tmp, mal)
    except BaseException:
        kalla = None
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    if ta_bort_hamtad:
        os.remove(hamtad)
    return Lagrad(sokvag=mal, format=FORMAT, storlek_byte=os.path.getsize(mal),
                  sha256=_sha256(mal), bredd_px=bredd, hojd_px=hojd)
