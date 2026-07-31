# `reference_stats` kennt keinen Session-Begriff

**Datum:** 2026-07-31 · **Art:** Befund, kein Code-Eingriff

## Kurzfassung

`reference_stats` ist ein reiner Cache über **alle** `reference_features`-Zeilen
eines Artikels. Es gibt darin **keinen Begriff von Einlern-Session**. Bekommt
ein Artikel Shots einer zweiten Session, ohne dass die erste vorher gelöscht
wird, verschmelzen beide still zu **einem** Mittelwert und **einem** σ — und σ
ist die Basis für `sigma_eff` im Matcher.

**Konsequenz für das anstehende Komplett-Neu-Enrollment: vor dem Neu-Einlernen
müssen ALLE Altreferenzen des Artikels gelöscht werden.** Sonst misst der
Matcher gegen eine Streuung, die aus zwei verschiedenen Aufbauten stammt.

## Beleg

`Database._recompute_stats` ([docodetect/database.py:284](../docodetect/database.py))
rechnet über das vollständige Ergebnis von `references_for(article_number)`.
Kein Filter, kein Zeitfenster, keine Session-Spalte. `add_reference` ruft es
nach jedem einzelnen Insert neu auf — das Ergebnis ist immer der Mittelwert
über den gesamten dann vorhandenen Bestand.

Der einzige Ort, an dem ein Session-Begriff überhaupt existiert, ist der
`{ts}`-Präfix im Dateinamen unter `paths.reference_dir` (`{ts_ms}_{i:02d}.png`,
ein `ts` je Aufnahme-Session). Ausgewertet wird er ausschliesslich von
`build_contour_band(session=…)`
([docodetect/enrollment_sheet.py:824](../docodetect/enrollment_sheet.py)) — per
Teilstring-Vergleich auf dem Dateinamen. **Die DB kennt ihn nicht.**

## Ist-Stand der Live-DB (2026-07-31, lesend geprüft)

| | |
|---|---|
| `reference_features` gesamt | 359 Zeilen |
| davon `image_path IS NULL` | 334 (Altbestand 20.–23.07.) |
| davon gesetzt | 25 — LOEFFEL-3 (12), MESSER-2 (12), CD-REFERENZ (1) |
| Artikel mit Zeilen aus **mehr als einem Kalendertag** | **keine** |

LOEFFEL-3 und MESSER-2 wurden am 28.07. neu eingelernt. Im Snapshot
`doco_detect_2026-07-28_pre-reenroll.sqlite3` haben beide je **9** Zeilen mit
`image_path = NULL`; in der Live-DB stehen je **12** Zeilen vom 28.07. und
`n_shots = 12`. Die Altzeilen wurden also entfernt, nicht ergänzt — der
Ablauf war richtig. Dass er richtig war, ist an den Zahlen aber **nicht
erkennbar**: eine Mischung hätte lediglich `n_shots = 21` und ein grösseres σ
ergeben, ohne Warnung und ohne Spur.

Genau das ist der Punkt: **Es gibt keinen Wächter.** Der einzige Schutz ist
das Vorgehen.

## Vorgehen beim Neu-Einlernen

1. `delete-article <nr>` (entfernt Artikel **und** Referenzen) oder gezielt die
   Referenzen löschen, dann den Artikel neu anlegen.
2. Neu einlernen.
3. Im Enrollment-Diagnoseblatt prüfen, dass `n_shots` der Shot-Zahl **dieser**
   Session entspricht. Steht dort mehr, sind Altzeilen stehengeblieben.

Zusatz für LOEFFEL-3: der Artikel ist ein bekannt harter Fall (σ(Ø) = 1,87 mm
aus den 9 Altbestands-Shots, ~2–4× die saubere C-Serie-Bandbreite). Das
Diagnoseblatt vor dem Vertrauen darauf ansehen — siehe CLAUDE.md,
„Enrollment-Diagnose".

## Warum das hier steht

Der `--sandbox`-Name ist deshalb **Pflicht und hat keinen Default**
([docodetect/config.py](../docodetect/config.py)): ein Sammelordner lüde dazu
ein, zwei Testläufe still in denselben Stand zu schreiben — und dort greift
genau dieser Mechanismus. Siehe
[2026-07-31-sandbox-isolierter-db-stand.md](2026-07-31-sandbox-isolierter-db-stand.md).
