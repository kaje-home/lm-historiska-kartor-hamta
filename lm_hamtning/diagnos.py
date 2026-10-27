"""Logg över QGIS-avslut, från pluginet självt (2026-10-08).

QGIS har flera gånger stängts utan felruta. Startskriptet i profilen
(`python/startup.py`) körs inte när QGIS startas från användarens genväg, så
loggen tas här i stället: pluginet laddas vid varje start. Till
`<profil>/historiska_kartor_avslut.log` skrivs

* stacken vid segfault eller abort (faulthandler, alla trådar),
* ohanterade Python-undantag (QGIS egen hantering körs som förut),
* ordnad avslutning (atexit), med de senaste händelserna pluginet noterat,

och pluginet noterar sina egna steg med `notera(text)`, så att loggen visar vad
som hände strax före ett avslut. Loggen byter namn till `.1` när den passerat
LOGG_HOGST byte, så att den inte växer för evigt på en främmande dator (inför
publiceringen 2026-10-27).
"""
from __future__ import annotations

import atexit
import faulthandler
import os
import sys
import time
import traceback
from collections import deque

LOGG_HOGST = 1_000_000

_logg = None
_senaste: deque = deque(maxlen=30)
_forra_hook = None


def _fil() -> str:
    try:
        from qgis.core import QgsApplication
        return os.path.join(QgsApplication.qgisSettingsDirPath(), "historiska_kartor_avslut.log")
    except Exception:                                      # noqa: BLE001
        return os.path.join(os.path.expanduser("~"), "historiska_kartor_avslut.log")


def notera(text: str) -> None:
    """Ett steg i pluginet; skrivs också direkt, så att det finns kvar efter en krasch."""
    rad = f"{time.strftime('%H:%M:%S')} {text}"
    _senaste.append(rad)
    if _logg is not None:
        try:
            _logg.write(rad + "\n")
        except Exception:                                  # noqa: BLE001
            pass


def _hook(t, v, tb):
    notera("ohanterat undantag:\n" + "".join(traceback.format_exception(t, v, tb)))
    if _forra_hook is not None:
        try:
            _forra_hook(t, v, tb)
        except Exception:                                  # noqa: BLE001
            pass


def _avslut() -> None:
    notera("ordnad avslutning (atexit)")


def starta() -> None:
    """En gång per QGIS-session; anrop nummer två gör inget."""
    global _logg, _forra_hook
    if _logg is not None:
        return
    fil = _fil()
    try:
        if os.path.getsize(fil) > LOGG_HOGST:
            os.replace(fil, fil + ".1")
    except OSError:
        pass
    try:
        _logg = open(fil, "a", buffering=1, encoding="utf-8")
    except OSError:
        return
    _logg.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} pid {os.getpid()}\n")
    try:
        faulthandler.enable(file=_logg, all_threads=True)
    except Exception:                                      # noqa: BLE001
        pass
    if getattr(sys.excepthook, "__name__", "") != "_hook":
        _forra_hook = sys.excepthook
        sys.excepthook = _hook
    atexit.register(_avslut)
