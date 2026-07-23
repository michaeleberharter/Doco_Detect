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
# 2. Die 19 Szenen aufnehmen (UI oder CLI) - landen in data/captures/
python -m docodetect.cli identify          # je Szene einmal, IDs notieren
# 3. Ansehen, nichts schreiben: Overlays prüfen, Flächen und Ära kontrollieren
python scripts/adopt_goldens.py --dry-run --overlay-dir /tmp/overlays \
    01-leere-box=<id>:raises 02-teeloeffel-flach=<id> ... \
    17-teller-randberuehrung=<id>:border 19-glastasse-transparent-2=<id>
# 4. Erst nach Sichtabnahme JEDER Maske: dasselbe Kommando ohne --dry-run
python -m pytest tests/test_real_captures.py -q      # muss grün sein
```

Zwei Suffixe: `:raises` (Segmentierung muss abbrechen) und `:border`
(Segmentierung muss `touches_border` melden). Alles andere ist eine
gewöhnliche Szene.

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

## Checkliste — 19 Szenen, in Aufnahme-Reihenfolge

Die Namen sind verbindlich: sie stehen als `PFLICHT_SZENEN` in
`tests/test_real_captures.py`, der Test verlangt genau diese. Eine Szene
aufzugeben ist erlaubt, aber nur als bewusste Änderung dieser Liste mit
Begründung im Commit.

Auswahlkriterium ist **Objektklasse × Fehlermechanismus**, keine runde Zahl.
Ähnliche Lagen derselben Klasse gelten ausdrücklich *nicht* als redundant:
die Segmentierung kalibriert pro Bild selbst, benachbarte Lagen können
verschiedene Kalibrier-Pfade treffen. Redundanz im Regressionsnetz ist Marge.

| ✓ | Szenen-ID | Objekt / Lage | Warum diese Szene |
|---|---|---|---|
| ☐ | `01-leere-box` `:raises` | **leere Box** | direkt nach `capture-background` schießen; muss `SegmentationError` werfen |
| ☐ | `02-teeloeffel-flach` | Teelöffel, flach | Grundfall Laffe |
| ☐ | `03-teeloeffel-diagonal` | Teelöffel, diagonal | Rotationslage |
| ☐ | `04-teeloeffel-gebogen` | Teelöffel, gebogen aufliegend | ungleichmäßige Auflage |
| ☐ | `05-teeloeffel-klein-dunkel` | kleiner Teelöffel, dunkel/matt | **Glow-Fringe auf kleiner Fläche** |
| ☐ | `06-gabel-flach-links` | Gabel flach, Zinken nach links | Zinkenschlitze müssen offen bleiben |
| ☐ | `07-gabel-flach-rechts` | Gabel flach, Zinken nach rechts | Gegenrichtung |
| ☐ | `08-gabel-flach` | Gabel flach, dritte Orientierung | Streuung über Lagen |
| ☐ | `09-gabel-diagonal` | Gabel diagonal | zweite Diagonale |
| ☐ | `10-gabel-diagonal-spiegelferse` | Gabel diagonal | **Spiegelferse** (Spiegelkeil mit eigener Umriss-Struktur) |
| ☐ | `11-gabel-vertikal` | Gabel **vertikal** | **Spiegelhals — Brückenfall** |
| ☐ | `12-messer-flach` | Messer, flach | **Spiegelstreifen über die ganze Klinge** |
| ☐ | `13-messer-diagonal` | Messer, diagonal | **Kropf im Spiegel → Zertrennungsfall** (Objekt zerfällt in zwei Komponenten) |
| ☐ | `14-servierloeffel` | Servierlöffel | große Laffe |
| ☐ | `15-servierloeffel-flach` | Servierlöffel, flach | große Laffe, andere Lage |
| ☐ | `16-teller-gross` | großer Teller, zentriert | großflächig, Fahne/Rand-Zone |
| ☐ | `17-teller-randberuehrung` `:border` | **größter Teller, Rand berührt** | FOV-Grenze; `touches_border` MUSS greifen — dokumentiert nebenbei das FOV-Ergebnis |
| ☐ | `18-glastasse-transparent` | Glastasse **mit Henkel** | **Transparent-Annex** |
| ☐ | `19-glastasse-transparent-2` | dieselbe Tasse, zweiter Schuss | Reproduzierbarkeit transparent |

Die Reihenfolge minimiert Handgriffe: leere Box zuerst (Box ist ohnehin
leer), dann klassenweise Teelöffel → Gabel → Messer → Servierlöffel →
Teller → Glas.

### Zur Randberührungs-Szene

`segment()` **wirft nicht** bei Randberührung — es setzt nur
`touches_border`; erst `Pipeline.analyze` macht daraus einen Fehler
([pipeline.py:261](../docodetect/pipeline.py#L261)). Diese Szene hält genau
diese Arbeitsteilung fest: verlernt die Segmentierung die Randberührung,
vermisst die Pipeline stillschweigend ein abgeschnittenes Objekt. Der Helfer
lehnt eine `:border`-Szene ab, die den Rand *nicht* berührt — und ebenso
eine gewöhnliche Szene, die ihn berührt.

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
