# Doku-Chronik

Landkarte für Sitzungen ohne Vorkontext: die Ergebnis- und Ablaufdokumente
in zeitlicher Reihenfolge, je ein Satz Inhalt. **Ersetzt kein Dokument** —
für die eigentliche Begründung immer das verlinkte Dokument lesen. Dauerregeln
stehen in [../CLAUDE.md](../CLAUDE.md), Architektur in
[architektur.md](architektur.md), Setup/Ablauf im [../README.md](../README.md).

## Ergebnis- & Ablaufdokumente (chronologisch)

- **2026-07-20** — [Regressions-Korpus Übergabebericht](superpowers/reports/2026-07-20-corpus-harness-abschluss.md):
  Aufbau der zweistufigen Korpus-Harness (Tier 1 Messung, Tier 2 Entscheidung),
  Fingerprints/Baseline/Drift-Zyklus.
- **2026-07-21** — [Vorfilter-Vergleichsfehler für längliche Artikel](superpowers/reports/2026-07-21-vorfilter-laengliche-artikel-ergebnis.md):
  Der Geometrie-Vorfilter vergleicht seither `max(width, depth)` statt
  `hypot` (Diagonal-vs-Länge-Fehler), plus Akzeptanz-Schicht.
- **2026-07-22** — [Testtag Mac — Ablaufplan](2026-07-22-testtag-mac.md):
  Ablauf der Mac-Messreihe (Vorbereitung für sigma_floors und Enrollment).
- **2026-07-22** — [sigma_floors aus einer echten Messreihe](superpowers/reports/2026-07-22-sigma-floors-ergebnis.md):
  Gemessene, versionierte sigma_floors in `config.yaml` (Ablösung der lokalen
  Werte, gegen die die alte Baseline fälschlich rechnete).
- **2026-07-23** — [Golden-Backstop](2026-07-23-golden-backstop.md):
  Schnittstelle zum Hardware-Block — welche Szenen an der Box aufzunehmen
  sind und wie sie als versionierte Segmentierungs-Goldens ins Repo kommen.
- **2026-07-23** — [Schritt 7: Metrik-Fix, phase-c-Korpus, mehrklassige Baseline](superpowers/reports/2026-07-23-phase-c-ergebnis.md):
  top1 rechnet roh gegen Label (Semantikwechsel), mehrklassiger Korpus,
  ehrliche Baseline; Rückenlage-Wächter.
- **2026-07-24** — [Windows-Eingangsprüfung + SQLite-Portabilität](superpowers/reports/2026-07-24-windows-eingangspruefung-ergebnis.md):
  Erster Windows-Lauf; SQLite-Versions-Unterschied gefixt, Tier-1-Drift
  gefunden, Schwellen-Sweep gesperrt.
- **2026-07-24** — [H-S-Drift-Attribution (arm64 ↔ x86-64)](superpowers/reports/2026-07-24-hs-drift-attribution-ergebnis.md):
  report-only — Zuordnung der Tier-1-Drift zum Plattformwechsel statt zu Code.
- **2026-07-24** — [Schwellen-Sweep — Betriebskurven (Block 2)](superpowers/reports/2026-07-24-schwellen-sweep-ergebnis.md):
  report-only — Betriebskurven (auto_accept vs. false_accept) aus
  Replay-Reports; Schwellen-ENTSCHEIDUNG erst nach Teller-Daten.
- **2026-07-24** — [stammdaten-Diagonal-Fix + sync-stammdaten](superpowers/reports/2026-07-24-stammdaten-sync-ergebnis.md):
  `stammdaten.py` rechnet noch mit `hypot` (dritte Diagonal-Fundstelle);
  `sync-stammdaten --apply` bleibt gesperrt, bis es dieselbe Nominalfunktion
  wie der Matcher nutzt.
- **2026-07-24** — [Arbeitsplan ab 2026-07-24](arbeitsplan-2026-07-24.md):
  aktueller Plan (Mac-first, Windows-Tag, Blöcke 1–5) — der lebende Fahrplan.
- **2026-07-31** — [`reference_stats` kennt keinen Session-Begriff](2026-07-31-reference-stats-keine-sessions.md):
  zwei Einlern-Sessions desselben Artikels verschmelzen still zu einem σ
  (Basis für `sigma_eff`) — vor dem Neu-Einlernen ALLE Altreferenzen löschen.
- **2026-07-31** — [Isolierter Testbestand `--sandbox NAME`](2026-07-31-sandbox-isolierter-db-stand.md):
  fünf Schreibpfade nach `data/sandbox/<name>/`, Kalibrierung bleibt geteilt
  (daher Sperren); enthält die bekannte Einschränkung `corpus/build.py:117`.

## Referenz (nicht chronologisch)

- [architektur.md](architektur.md) — zweistufige Pipeline, Modulgrenzen, Messpfad.
- Pläne/Specs: [superpowers/plans/](superpowers/plans/), [superpowers/specs/](superpowers/specs/).
