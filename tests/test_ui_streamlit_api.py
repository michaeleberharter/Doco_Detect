"""Schluckt eine Streamlit-Funktion unsere Keyword-Argumente still?

Anlass (2026-07-22): `st.plotly_chart(fig, width="stretch")` sah wie ein
Fix aus, ist aber die API einer NEUEREN Streamlit-Version. In 1.50 kennt
`plotly_chart` kein `width` — das Argument fiel in `**kwargs`, wurde
wirkungslos verworfen und loeste bei jedem Rendern die Deprecation-Warnung
"The keyword arguments have been deprecated ... Use `config` instead" aus.

Weder Import noch Syntaxpruefung noch ein AppTest-Durchlauf faellt darueber,
weil `**kwargs` alles annimmt. Darum dieser statische Abgleich: jedes
Keyword, das wir an eine `st.*`-Funktion uebergeben, muss in deren Signatur
benannt vorkommen. `st.dataframe`/`st.image` HABEN `width` — die duerfen es
weiter benutzen; der Test prueft je Funktion einzeln.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
import streamlit as st

WURZEL = Path(__file__).resolve().parent.parent
DATEIEN = sorted([*(WURZEL / "pages").glob("*.py"), WURZEL / "app.py"])


def _aufrufe(pfad: Path):
    """(Zeile, Funktionsname, [Keywords]) je st.<name>(...)-Aufruf."""
    baum = ast.parse(pfad.read_text(encoding="utf-8"), filename=str(pfad))
    for knoten in ast.walk(baum):
        if not isinstance(knoten, ast.Call):
            continue
        f = knoten.func
        if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                and f.value.id == "st"):
            keywords = [k.arg for k in knoten.keywords if k.arg]
            if keywords:
                yield knoten.lineno, f.attr, keywords


def _erlaubte_keywords(name: str) -> set | None:
    """Benannte Parameter der Streamlit-Funktion; None, wenn es sie hier
    nicht gibt (dann hat der Test nichts zu sagen)."""
    fn = getattr(st, name, None)
    if fn is None or not callable(fn):
        return None
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    return {n for n, p in sig.parameters.items()
            if p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)}


@pytest.mark.parametrize("pfad", DATEIEN, ids=lambda p: p.name)
def test_keine_stillschweigend_verschluckten_keywords(pfad):
    if not pfad.exists():
        pytest.skip(f"{pfad.name} existiert nicht")
    befunde = []
    for zeile, name, keywords in _aufrufe(pfad):
        erlaubt = _erlaubte_keywords(name)
        if erlaubt is None:
            continue
        for kw in keywords:
            if kw not in erlaubt:
                befunde.append(
                    f"{pfad.name}:{zeile} st.{name}({kw}=...) — "
                    f"kein Parameter dieser Streamlit-Version "
                    f"({st.__version__}); landet in **kwargs und wirkt nicht")
    assert not befunde, "\n" + "\n".join(befunde)


def test_der_test_wuerde_den_echten_fall_fangen(tmp_path):
    """Selbstkontrolle: genau das Muster von damals muss auffallen."""
    p = tmp_path / "regression.py"
    p.write_text('import streamlit as st\n'
                 'st.plotly_chart(fig, width="stretch")\n', encoding="utf-8")
    aufrufe = list(_aufrufe(p))
    assert aufrufe == [(2, "plotly_chart", ["width"])]
    assert "width" not in _erlaubte_keywords("plotly_chart")


def test_dataframe_darf_width_behalten():
    """Gegenprobe: der Test darf nicht pauschal jedes width verbieten."""
    assert "width" in _erlaubte_keywords("dataframe")
    assert "width" in _erlaubte_keywords("image")
