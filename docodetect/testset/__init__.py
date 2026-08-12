"""Real-Capture-Testset: eingefrorene Aufnahmen samt Aufnahmezustand.

Gegenstueck zum Regressions-Korpus (docodetect/corpus), aber mit
umgekehrter Beweisrichtung: der Korpus REKONSTRUIERT den Zustand alter
Reports heuristisch (recover_*, db_match_ratio), dieses Paket liest ihn
AUSSCHLIESSLICH aus dem `zustand`-Block, den pipeline.aufnahme_zustand
seit 2026-08-12 beim Speichern jedes Reports schreibt. Es gibt hier
bewusst keine Rekonstruktionslogik — ein Report ohne zustand-Block wird
uebersprungen und gemeldet, nie erraten.

Der Datenbestand entsteht an der Windows-Box (docs/2026-08-12-testset-
windows-inbetriebnahme.md); am Mac laufen nur Struktur- und Codepruefung
(Trockenlauf auf smoke_testset-Material). Das Replay ist REIN BERICHTEND,
kein Merge-Gate — Tier 1/2 des Korpus bleiben unveraendert das Gate.

Ablage ausserhalb des Repos (paths.testset_dir); versioniert ist nur
testset/manifest.json.
"""
