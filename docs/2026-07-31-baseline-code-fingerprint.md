# Baseline vom 2026-07-24 trägt einen `code_fingerprint` von vor der Messpfad-Runde

**Datum:** 2026-07-31 · **Art:** Befund. Nichts geändert, kein Re-Baselining.

## Befund

`corpus/baseline.json` (`run_id: 20260724-baseline-post-sync-final`, Tier 2,
n=104) führt

```
code_fingerprint: 5f4e90b679bdce3c38fb1039d2d520e89b792df83976bd29af9f24fd4892601d
```

Ein Tier-2-Lauf am 2026-07-31 (`runs/20260731-180249`) liefert einen **anderen**
`code_fingerprint`. Der `config_fingerprint` ist identisch.

## Herkunft

`code_fingerprint` hasht die zehn Dateien aus `CODE_DATEIEN`
([docodetect/corpus/runner.py:37](../docodetect/corpus/runner.py)) plus
`corpus/accepted_deltas/*.json`. Zwischen dem Baseline-Datum und dem 2026-07-31
haben fünf Commits Dateien aus dieser Liste verändert:

| Commit | Datum | |
|---|---|---|
| `a588e52` | 2026-07-25 | fix(calibration): Artefakte archivieren statt überschreiben |
| `67dbd08` | 2026-07-28 | enroll: Referenz-Shots verlustlos als PNG |
| `2603641` | 2026-07-28 | enrollment-sheet: Diagnoseblatt aus den N Shots |
| `59edc46` | 2026-07-29 | Messpfad-Runde: Prefilter-Liste, lat_p98, µs-timestamp |
| `504ad8a` | 2026-07-29 | Enrollment-Blatt beim „Übernehmen" automatisch sichern |

Der Sandbox-Commit `f117a92` (2026-07-31) ist **nicht** darunter: er berührt
keine der `CODE_DATEIEN`.

## Wirkung

- Auf `corpus-run --check` **keine**: das Gate urteilt über Quoten und
  Mess-Deltas. Beide Läufe vom 2026-07-31 sind Exit 0, alle Tier-2-Quoten
  decken sich exakt mit der Baseline (`false_accept_rate` 0/44).
- Auf `--changed-only`: der `code_fingerprint` invalidiert den Ergebnis-Cache.
  Solange der Baseline-Wert von vor der Messpfad-Runde stammt, rechnet ein
  `--changed-only`-Lauf mehr neu als nötig.

## Status

Unverändert gelassen. Kein `--update-baseline` ausgeführt.
