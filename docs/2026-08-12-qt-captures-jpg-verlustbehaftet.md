# Qt-Ära-Captures wurden verlustbehaftet gespeichert (JPG) — Befund und Fix

**Datum:** 2026-08-12 · **Betrifft:** `pipeline._save_capture_and_report` ·
**Status:** behoben (PNG seit diesem Commit)

## Befund

Seit der Qt-Umstellung speicherte `_save_capture_and_report` Live-Frames als
`{ts}.jpg` — verlustbehaftet. Der MatchReport entsteht aber auf dem **rohen**
Frame: wer das JPG erneut durchrechnet, misst andere Pixel als die
Identifikation, die der Report dokumentiert. Damit sind diese Aufnahmen nicht
exakt nachrechenbar — dieselbe Klasse von Beweislücke wie der dokumentierte
`image_path`-NULL-Fall.

Zusätzlich war `paths.save_captures` („jede UI-Aufnahme als Roh-PNG …") seit
dem Streamlit-Aus (2026-08-01, Commit `07586b5`) ein **toter Key**: kein Code
las ihn mehr, der Kommentar in `config.yaml` beschrieb einen entfernten
Zustand. Der PNG-Speicherpfad der Streamlit-Ära ist mit der App verschwunden;
die Qt-UI lief seither ausschließlich über den JPG-Pfad der Pipeline.

## Betroffener Bestand

`data/captures/` am 2026-08-12: 595 PNG (Streamlit-Ära, exakt nachrechenbar),
**26 JPG (Qt-Ära, nicht exakt nachrechenbar)**, 23 Report-JSONs. Die 26 JPGs
bleiben liegen (Bewertungen und Reports sind gültig — nur die pixelgenaue
Reproduktion der Messung ist für sie nicht möglich). Sie werden NICHT in das
Real-Capture-Testset (`docodetect/testset`) aufgenommen; der Datenbestand des
Testsets startet ohnehin erst an der Windows-Box bei null.

## Fix (dieser Commit)

- Live-Captures wieder als **verlustfreies PNG**.
- `paths.save_captures` **wieder verdrahtet** (Default `true`): schaltet nur
  das Bild ab, das Report-JSON (Bewertungs-Rückschreibung, Batch-Analyse)
  wird immer geschrieben.
- Jeder gespeicherte Report trägt jetzt einen `zustand`-Block
  (`pipeline.aufnahme_zustand`): Hashes von Kalibrierung, Hintergrund,
  DB-Stand, features-/matching-Config plus Plattform/Versionen. Damit ist der
  Aufnahmezustand ab jetzt **beim Schreiben** bestimmt statt beim Lesen
  rekonstruiert (Hintergrund: `docodetect/corpus/bundle.py` konnte ihn aus
  Alt-Reports nur heuristisch trennen, nie ersetzen).
