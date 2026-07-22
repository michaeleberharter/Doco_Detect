# Golden-Backstop — Übernahme am 2026-07-23

Teil A (Testumbau, Helfer, Doku) liegt auf `feature/golden-backstop`.
Dieses Dokument ist die Schnittstelle für den Hardware-Block: **was an der
Box aufzunehmen ist und wie es ins Repo kommt.**

Hintergrund und Verlustchronik: README, Abschnitt „Tests und Hardware".

---

## So läuft die Übernahme (Kurzfassung)

```bash
# 1. Hintergrund neu aufnehmen (leere Box) - definiert die Beleuchtungs-Ära
python -m docodetect.cli capture-background
# 2. Die 15 Szenen aufnehmen (UI oder CLI) - landen in data/captures/
python -m docodetect.cli identify          # je Szene einmal, IDs notieren
# 3. Ansehen, nichts schreiben: Overlays prüfen, Flächen und Ära kontrollieren
python scripts/adopt_goldens.py --dry-run --overlay-dir /tmp/overlays \
    01-teeloeffel-flach=<id> 02-teeloeffel-diagonal=<id> ... 15-leere-box=<id>:raises
# 4. Erst nach Sichtabnahme JEDER Maske: dasselbe Kommando ohne --dry-run
python -m pytest tests/test_real_captures.py -q      # muss grün sein
```

## Erwartete Struktur danach

```
tests/fixtures/golden_captures/
├── background.png          # der Hintergrund aus Schritt 1 (mitversioniert!)
├── goldens.json            # je Szene: kind, area_px, Quelldateiname
└── scenes/
    ├── 01-teeloeffel-flach.png
    ├── …
    └── 15-leere-box.png
```

`goldens.json` schreibt der Helfer, nicht die Hand. Rechts vom `=` steht die
Capture-ID aus `data/captures/` (ohne `.png`) oder ein Pfad.

## Checkliste — 15 Szenen

Die Namen sind verbindlich: sie stehen als `PFLICHT_SZENEN` in
`tests/test_real_captures.py`, der Test verlangt genau diese. Eine Szene
aufzugeben ist erlaubt, aber nur als bewusste Änderung dieser Liste mit
Begründung im Commit.

| ✓ | Szenen-ID | Objekt / Lage | Warum diese Szene |
|---|---|---|---|
| ☐ | `01-teeloeffel-flach` | Teelöffel, flach | Grundfall Laffe |
| ☐ | `02-teeloeffel-diagonal` | Teelöffel, diagonal | Rotationslage |
| ☐ | `03-teeloeffel-gebogen` | Teelöffel, gebogen aufliegend | ungleichmäßige Auflage |
| ☐ | `04-teeloeffel-klein-dunkel` | kleiner Teelöffel, dunkel/matt | **Glow-Fringe-Fall** |
| ☐ | `05-gabel-flach-links` | Gabel flach, Zinken nach links | Zinkenschlitze müssen offen bleiben |
| ☐ | `06-gabel-flach-rechts` | Gabel flach, Zinken nach rechts | Gegenrichtung |
| ☐ | `07-gabel-vertikal` | Gabel **vertikal** | **Spiegelhals — Brückenfall** |
| ☐ | `08-gabel-diagonal-spiegelferse` | Gabel diagonal | **Spiegelferse** |
| ☐ | `09-gabel-diagonal` | Gabel diagonal, andere Lage | zweite Diagonale |
| ☐ | `10-gabel-flach` | Gabel flach, dritte Orientierung | Streuung über Lagen |
| ☐ | `11-servierloeffel` | Servierlöffel | große Laffe |
| ☐ | `12-servierloeffel-flach` | Servierlöffel, flach | große Laffe, andere Lage |
| ☐ | `13-glastasse-transparent` | Glastasse **mit Henkel** | **Transparent-Annex** |
| ☐ | `14-glastasse-transparent-2` | dieselbe Tasse, zweiter Schuss | Reproduzierbarkeit transparent |
| ☐ | `15-leere-box` | **leere Box** | muss `SegmentationError` werfen |

Zusammensetzung entspricht dem verlorenen Bestand: die harten Fälle, an denen
die Segmentierung 2026-07-16 abgenommen wurde.

## Worauf beim Abnehmen zu achten ist

Aus dem Abnahmeprotokoll von 2026-07-16 — das sind die Kriterien, gegen die
die alten Goldens freigegeben wurden:

- Laffen vollständig gefüllt, keine Löcher
- Gabel-Zinkenschlitze **offen** (nicht zugeschmiert)
- Spiegelnde Hälse/Fersen **überbrückt**, nicht abgerissen
- kein Glow-Fringe (heller Saum um das Objekt)
- Konturen eng am Objekt
- kein Objekt berührt den Bildrand (`touches_border` muss falsch sein)

## Fallstricke, die der Helfer selbst abfängt

- **Ära-Abstand**: passt eine Szene nicht zum Hintergrund (Median-|diff| > 6),
  bricht der Helfer mit Exit 1 ab und schreibt nichts. Dann Hintergrund neu
  aufnehmen **oder** die Szene neu schießen — nie übernehmen.
- **`:raises` ohne Ausnahme**: ist die Box bei `15-leere-box` nicht wirklich
  leer, meldet der Helfer das statt ein sinnloses Golden abzulegen.
- **Segmentierungs-Abbruch bei einer Objekt-Szene**: wird als unbrauchbar
  gemeldet, nicht stillschweigend übersprungen.
- **Nachziehen einzelner Szenen** ist möglich: ein zweiter Lauf ergänzt das
  Manifest, statt es zu ersetzen.

## Danach (Teil B, nicht heute Nacht)

Nach erfolgreicher Übernahme: vollständiger Testlauf, `corpus-run --tier 1
--check` **und** `--tier 2 --check`, dann `feature/golden-backstop` per
`--no-ff` nach `main`. Main sieht nur den fertigen, grünen Gesamtzustand.
