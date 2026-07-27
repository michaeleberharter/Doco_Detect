"""Pinning-Test fuer die Neu-Ableitungs-Logik des Schwellen-Sweeps
(scripts/schwellen_sweep.py::rederive) — REPORT-ONLY-Werkzeug, aendert nichts.

Der Sweep leitet Accept/Ambiguous/Reject aus gespeicherten MatchReports NEU AB,
statt Segmentierung/Features/Matcher neu zu rechnen. Diese Neu-Ableitung MUSS
bitgenau die Gate-Logik aus matcher.match() (Z. 341-365) nachbilden, sonst sind
alle Betriebskurven wertlos. Hier wird sie gegen SYNTHETISCHE MatchReports
gepinnt — korpus-UNABHAENGIG, damit der Test ohne lokalen Korpus laeuft.

Die volle Baseline-Quoten-Reproduktion (0/104 gegen win-postfix-tier2/replay/)
bleibt bewusst der Laufzeit-`pinning_check()` IM Werkzeug: sie haengt an einem
Run-Artefakt ausserhalb des Repos und waere als pytest-Fixture fragil.
"""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docodetect.matcher import CandidateReport, MatchReport  # noqa: E402

_QUELLE = Path(__file__).resolve().parent.parent / "scripts" / "schwellen_sweep.py"
_spec = importlib.util.spec_from_file_location("schwellen_sweep", _QUELLE)
sweep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sweep)

PROD_Z, PROD_M = 3.5, 2.0


def _cand(article="A", has_refs=True):
    return CandidateReport(
        article_number=article, name=article, nominal_size_mm=180.0,
        height_mm=10.0, corrected_diameter_mm=180.0, geometry_error_mm=0.0,
        has_references=has_refs, n_shots=3,
    )


def _report(max_z, llr, has_refs=True, n_cand=2, label=None, top1="A"):
    cands = [] if n_cand == 0 else [_cand(top1, has_refs)]
    cands += [_cand(f"B{i}", True) for i in range(1, n_cand)]
    return MatchReport(decision="", message="", candidates=cands,
                       max_z_winner=max_z, llr_margin=llr, label=label)


def test_rederive_pins_decision_logic():
    """rederive() reproduziert die Zwei-Gate-Logik exakt — bei den
    Produktionsschwellen (3,5/2,0) UND abseits davon (Z-/M-Achse, Grenzen)."""
    rd = sweep.rederive

    # --- Produktionsschwellen (3,5/2,0): die vollstaendige Wahrheitstabelle ---
    # kein Kandidat -> reject (unabhaengig von den Schwellen)
    assert rd(_report(1.5, 3.0, n_cand=0), PROD_Z, PROD_M) == "reject"
    # max_z_winner None -> reject
    assert rd(_report(None, 3.0), PROD_Z, PROD_M) == "reject"
    # z-Gate: max_z ueber der Schwelle -> reject, selbst bei riesiger Margin
    assert rd(_report(4.0, 99.0), PROD_Z, PROD_M) == "reject"
    # Einzelkandidat (llr None) mit Referenzen und z<=Z -> accept
    assert rd(_report(1.5, None, n_cand=1), PROD_Z, PROD_M) == "accept"
    # z<=Z, llr>=M, Referenzen -> accept
    assert rd(_report(1.5, 2.5), PROD_Z, PROD_M) == "accept"
    # z<=Z, aber llr unter M -> ambiguous (der Knick-Fall LOEFFEL-3)
    assert rd(_report(1.506, 1.9735), PROD_Z, PROD_M) == "ambiguous"
    # z<=Z, llr>=M, aber KEINE Referenzen -> ambiguous
    assert rd(_report(1.5, 2.5, has_refs=False), PROD_Z, PROD_M) == "ambiguous"

    # --- Grenzen sind inklusiv: max_z == Z -> zaehlt noch, llr == M -> Accept ---
    assert rd(_report(PROD_Z, PROD_M), PROD_Z, PROD_M) == "accept"

    # --- M-Achse: der Knick bei 1,9735 verschiebt sich mit der Schwelle ---
    knee = _report(1.506, 1.9735)
    assert rd(knee, PROD_Z, 1.97) == "accept"      # M gelockert -> Zwilling wird gebucht
    assert rd(knee, PROD_Z, 1.98) == "ambiguous"   # M straffer  -> weiterhin verweigert
    assert rd(knee, PROD_Z, PROD_M) == "ambiguous"  # Betriebspunkt: verweigert

    # --- Z-Achse: ein Reject bei max_z=4,25 tritt erst ueber Z=4,25 als Accept ein ---
    zcase = _report(4.25, 3.0)
    assert rd(zcase, PROD_Z, PROD_M) == "reject"   # Betriebs-Z 3,5: bleibt reject
    assert rd(zcase, 4.25, PROD_M) == "accept"     # Z == 4,25: Grenze inklusiv -> accept
    assert rd(zcase, 4.5, PROD_M) == "accept"      # Z gelockert -> Accept

    # --- z-Gate dominiert die Margin: hohe llr rettet ein z-Reject nicht ---
    assert rd(_report(4.0, 99.0), PROD_Z, 0.0) == "reject"
