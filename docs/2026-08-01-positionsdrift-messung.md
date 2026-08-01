# Die gemessene Länge hängt davon ab, WO in der Box das Objekt liegt

**Datum:** 2026-08-01 (Messung vom 2026-07-28, hier erstmals ausgewertet und
dokumentiert) · **Art:** Messbefund. Kein Code, keine Config, keine Baseline
geändert.
**Rohdaten:** `data/reference/MESSER-2/1785265604728_*.png` (12 Shots) ·
**Nachrechenbar:** `.venv/bin/python scripts/positionsdrift_check.py`

> **Kurzfassung:** Über eine vertikale Positionsleiter von 109 mm fällt die
> gemessene Länge von MESSER-2 um **8,56 mm** — monoton, mit **r = −0,997**.
> Das sind **0,037 % je Millimeter** Verschiebung. Der Effekt ist eine
> Eigenschaft der Position, nicht der Zeit; die Leiter kehrt in der Mitte um,
> und die Länge kehrt mit ihr um.
>
> **Warum das bisher niemand gesehen hat:** Die Prüfung vom 2026-07-27 hat die
> Position als **radialen, vorzeichenlosen** Abstand vom Bildmitte gemessen.
> Gegen diese Größe ist ein monotoner Gradient unsichtbar — oben und unten
> haben denselben Radius und entgegengesetzte Fehler, sie heben sich auf.
> In genau diesen zwölf Shots: **r = −0,997 gegen die vorzeichenbehaftete
> y-Position, r = −0,27 gegen den Radius.** Derselbe Datensatz, dieselbe
> Messgröße, zwei Antworten.

---

## 1. Warum es dieses Dokument gibt

Die Zahl „8,6 mm über die halbe Bildhöhe" trägt seit dem 28.07. drei
Dokumente — den [Fixpunkt-Test](2026-08-01-fixpunkt-test-scoring.md) (als
Prämisse der ganzen Fragestellung), den
[w(s)-Negativbefund](2026-08-01-wprofil-negativbefund.md) (als alleinige
Grundlage der Betriebs-Floor-Abschätzung 0,50–0,89 mm, an der die Absage
hängt) und seit heute den [Ablaufzettel](2026-07-31-ablauf-enrollment-session.md)
(als Begründung der Pflicht zur verteilten Auflage).

Ein eigenes Dokument hatte sie nicht. Aufbau, Rohdaten und Auswertung standen
nirgends, und sie widersprach offen einem Abschnitt, der am 2026-07-27
ausdrücklich als „der wertvollste Teil" der damaligen Analyse markiert wurde.
Das wird hier nachgeholt — und die Auflösung des Widerspruchs steht in
Abschnitt 5.

---

## 2. Aufbau

Die zwölf Shots sind **keine gewöhnliche Einlernserie**, auch wenn sie als
Referenzen von MESSER-2 in der DB stehen. Es ist eine **Positionsleiter**:
das Objekt wurde in etwa gleichen Schritten vertikal durch das Bildfeld
geschoben, Shots 00–05 in die eine Richtung, 06–11 in die andere. Die Umkehr
in der Mitte ist die Kontrolle, die Zeit von Position trennt (Abschnitt 4).

Die x-Position bleibt dabei fast konstant (Spanne 7,7 mm), die y-Position
überstreicht **109,4 mm = 64 % der Feldhöhe**.

**Die Messumgebung musste auf den Stand vom 28.07. zurückgesetzt werden**,
sonst misst man den Aufbau von heute:

| | Datei | Warum diese |
|---|---|---|
| Kalibrierung | `calibration-20260731-185137.json` | `mm_per_px` 0,07876574, erstellt 2026-07-20, bis 31.07. in Kraft — am 28.07. also gültig |
| Hintergrund | `background-20260731-165437.png` | mtime 28.07. 20:51, 4K; der Stand, der beim Enrollment um 21:06 in Kraft war |

**Falle, in die ich zuerst getappt bin:** `background-20260728-205102.png` sieht
nach dem passenden Archiv aus, ist aber **1080p** — er stammt aus einem
Auflösungs-Zwischenfall desselben Abends (drei Hintergrund-Aufnahmen zwischen
20:48 und 20:51, zwei davon in 1080p). Gegen ihn scheitert jede Segmentierung
der 4K-Shots mit `Image (2160, 3840, 3) vs background (1080, 1920, 3)
mismatch`. Der Archivname trägt den Zeitpunkt der **Archivierung**, nicht den
der Aufnahme — wer nach Datum greift, greift daneben.

Alles rein lesend: keine DB, keine Config-Datei, keine Kalibrierung wird
angefasst; die Umgebung wird nur im Speicher gesetzt.

---

## 3. Rohdaten

Nach y sortiert (negativ = oberhalb der Bildmitte). `Ø` ist
`circle_diameter_mm` aus dem Messpfad, `ext_full` und `lat_p98` sind
kontur-abgeleitet.

| Shot | ext_full [mm] | lat_p98 [mm] | Ø [mm] | x [mm] | y [mm] |
|---|---|---|---|---|---|
| 05 | 216,04 | 21,92 | 216,13 | −7,3 | **−48,8** |
| 04 | 215,41 | 21,67 | 215,50 | −5,8 | −40,8 |
| 03 | 214,70 | 21,52 | 214,79 | −5,1 | −31,5 |
| 02 | 213,67 | 21,21 | 213,74 | −11,7 | −19,6 |
| 01 | 212,72 | 20,91 | 212,80 | −9,2 | −9,6 |
| 00 | 211,94 | 20,65 | 211,98 | −7,9 | +1,2 |
| 06 | 211,79 | 20,53 | 211,85 | −7,9 | +12,8 |
| 07 | 210,22 | 20,29 | 210,24 | −12,8 | +21,3 |
| 08 | 209,50 | 20,09 | 209,55 | −10,6 | +30,6 |
| 09 | 208,78 | 19,97 | 208,85 | −8,4 | +41,5 |
| 10 | 208,32 | 19,90 | 208,34 | −11,1 | +49,0 |
| 11 | 207,47 | 19,66 | 207,50 | −10,0 | **+60,6** |

Beide Längenschätzer laufen praktisch deckungsgleich (`Ø` − `ext_full` liegt
durchweg bei 0,02–0,09 mm). Der Effekt ist also keine Eigenheit von
`ext_full`; er sitzt in der Messung der Länge selbst.

---

## 4. Auswertung

**Spanne 8,56 mm** (207,47 … 216,04) über 109,4 mm Weg.
**Steigung −0,0791 mm/mm** = **−0,0374 % je mm** Verschiebung.

| Bezugsgröße | Pearson r |
|---|---|
| y-Position, **vorzeichenbehaftet** | **−0,997** |
| radialer Abstand von der Bildmitte (vorzeichenlos) | −0,270 |
| Shot-Index (Zeit) | −0,738 |

### Es ist die Position, nicht die Zeit

Der Verdacht liegt nahe, weil sich über eine Session vieles ändern kann
(Fokus, Beleuchtung, Temperatur). Die Leiter beantwortet ihn durch ihre
Konstruktion:

| Abschnitt | y läuft | ext_full läuft |
|---|---|---|
| Shots 00 → 05 | +1,2 → −48,8 mm (nach oben) | 211,94 → **216,04** (steigt) |
| Shots 06 → 11 | +12,8 → +60,6 mm (nach unten) | 211,79 → **207,47** (fällt) |

Die Zeit läuft in beiden Hälften vorwärts, die Länge in **entgegengesetzte**
Richtungen. Eine Drift über die Session kann das nicht erzeugen. Entsprechend
erklärt die Position 99,4 % der Varianz (r² = 0,994), der Zeitindex nur
54 % — und dessen Rest-Korrelation ist geliehen, weil Index und Position im
Versuchsaufbau teilweise mitlaufen.

### Die Breite fällt schneller als die Länge

| Größe | relative Steigung | über die Leiter |
|---|---|---|
| `ext_full` | −0,0374 % je mm | −3,97 % |
| `lat_p98` | **−0,0996 % je mm** | **−10,31 %** |

Faktor **2,66**, und `lat_p98` ist über alle zwölf Shots monoton — also kein
Rauschen. **Eine reine Vergrößerungsänderung würde beide Größen gleich
skalieren.** Das tut sie nicht, der Effekt ist damit nicht allein ein
Maßstabsfehler.

Kandidaten, zwischen denen diese Daten **nicht** entscheiden: eine schräg
stehende Kamera (Keystone), die schräge Sicht auf ein Objekt mit Höhe
(Klinge und Griff liegen nicht in einer Ebene), oder eine positionsabhängige
Kantenlage der Segmentierung durch Beleuchtungs- und Schattenverlauf. Das zu
trennen braucht ein Raster über das ganze Feld, nicht eine Linie — siehe
Abschnitt 7.

---

## 5. Die Auflösung mit dem Orientierungs-Test vom 2026-07-27

[docs/2026-07-27-scoring-analyse.md, Abschnitt 9](2026-07-27-scoring-analyse.md)
prüfte über 104 Korpus-Reports den Zusammenhang von `s_len` mit der
Aufnahmegeometrie und fand **keinen einzigen tragenden Fit** (alle |r| ≤ 0,29;
`s_len ~ r_end_max` −0,09, `~ theta` −0,17, `~ r_centroid` −0,16). Abschnitt 5
desselben Dokuments erklärt Parallaxen-Scherung und randnahe Verzeichnung für
widerlegt, Abschnitt 9 schließt: „**Aufnahmegeometrie als Ursache des
Tail-Effekts ist ausgeschlossen.**"

**Der Widerspruch löst sich, und zwar schärfer als über „Korpus gegen
kontrolliertes Experiment".** Die naheliegende Erklärung wäre, dass ein
gewachsener Korpus die Position nicht systematisch variiert und der Effekt
deshalb im Rauschen verschwindet. Das stimmt auch — aber es ist nicht der
Kern. Der Kern ist die **Wahl der Positionsvariable**:

> `r_centroid`, `r_end_max` und `r_quer_max` sind **radiale, vorzeichenlose**
> Abstände von der Bildmitte. Ein **monotoner, vorzeichenbehafteter** Gradient
> ist gegen sie strukturell unsichtbar: ein Objekt 40 mm oberhalb und eines
> 40 mm unterhalb der Mitte haben denselben Radius, aber **entgegengesetzte**
> Längenfehler. Über beide Hälften gemittelt hebt sich die Korrelation auf.

Das ist nicht argumentiert, sondern **an denselben zwölf Shots vorgeführt**:
sie enthalten einen Effekt mit r = −0,997 gegen die vorzeichenbehaftete
Position — und liefern gegen den **radialen** Abstand **r = −0,270**, also
denselben Nullbefund, den das 07-27-Dokument über 104 Bilder gemeldet hat.
Ein kontrolliertes Experiment, mit der radialen Variable ausgewertet, hätte
2026-07-27 ebenfalls nichts gefunden.

### Was davon steht und was nicht

| Aussage von 2026-07-27 | Status heute |
|---|---|
| „Radiale Verzeichnung / Parallaxen-Scherung erzeugt den **Tail**-Effekt" — widerlegt | **steht.** Diese Messung sagt nichts über die acht Tail-Ausreißer; sie misst den Bulk. |
| „`s_len` korreliert über alle 104 Reports **nicht** mit der Schwerpunktlage" | **steht als Zahl**, ist aber gegen eine radiale Variable gerechnet und deshalb blind für einen signierten Gradienten. |
| „**Aufnahmegeometrie als Ursache ausgeschlossen**" | **zu weit formuliert.** Ausgeschlossen ist eine radialsymmetrische Ursache. Ein linearer vertikaler Gradient war nie geprüft und ist nicht ausgeschlossen — er ist jetzt gemessen. |

**Damit ist auch meine eigene frühere Zuspitzung zu korrigieren:** die Notiz
„der 28.07.-Befund widerlegt ‚Verzeichnung ausgeschlossen'" ist zu grob.
Widerlegt ist die **Positionsunabhängigkeit der Längenmessung**, nicht die
Tail-Diagnose von 2026-07-27. Zwei verschiedene Phänomene, und nur eines ist
hier gemessen.

---

## 6. Was das für den Betriebs-Floor heißt — und damit für w(s), D7 und D8

Der [w(s)-Negativbefund](2026-08-01-wprofil-negativbefund.md) rechnet einen
relativen Maßstabsfehler von k % in einen Profil-Floor um über
k · RMS(w(s)), mit RMS(w) = 12,6–22,2 mm. Mit „8,6 mm über die halbe
Bildhöhe → 4,0 %" ergab das **0,50–0,89 mm**.

**Die Zahl ist reproduziert, ihre Beschriftung war falsch.** Die 8,56 mm
stehen über **64 %** der Feldhöhe, nicht über die halbe. Als Rate gerechnet:

| unterstellte Auflage-Streuung | Drift | relativ | → Floor |
|---|---|---|---|
| die beobachtete Leiter (109 mm) | 8,66 mm | 4,09 % | **0,52–0,91 mm** |
| halbe Feldhöhe (85 mm) | 6,73 mm | 3,18 % | 0,40–0,71 mm |
| volle Feldhöhe (170 mm) | 13,47 mm | 6,36 % | **0,80–1,41 mm** |

Die dokumentierten 0,50–0,89 mm entsprechen genau der ersten Zeile — die
Herleitung hat also die **beobachtete Spanne** verwendet und sie „halbe
Bildhöhe" genannt. Der Wert stimmt, die Begründung war ungenau.

**Der Befund für die offene w(s)-Frage ist damit unbequem.** Nachtrag 11 des
Negativbefunds hält fest, dass die Entscheidung an der Grenze **σ_floor =
1,0 mm** hängt: darunter ist w(s) mit hohem Gewicht ein ernsthafter Kandidat,
darüber ist der Gewinn weg. Die drei Zeilen oben spannen **0,40 bis 1,41 mm** —
sie liegen also auf **beiden Seiten** dieser Grenze, je nachdem, wie weit man
die Auflage im Betrieb streuen lässt. Und diese Streuung ist **nicht
gemessen**.

**Die Grundlage von w(s)/D7/D8 wackelt also nicht, weil der Positionseffekt
unsicher wäre — er ist sauberer belegt als vorher (r = −0,997). Sie wackelt,
weil die entscheidende Größe von einer unbeobachteten Betriebsannahme abhängt,
und der Faktor zwischen deren Extremen ist 3,5.** Die Absage an w(s) bleibt
richtig, aber ihr Grund ist noch schmaler als im Negativbefund beschrieben:
nicht „der Floor liegt zu hoch", sondern „der Floor ist nicht bekannt, und
sein plausibler Bereich umspannt die Entscheidungsgrenze".

Praktische Folge, die nichts kostet: **eine Auflage-Zone verkleinert den
Floor.** Wer die Objekte im Betrieb auf ein mittiges Feld von ±40 mm
beschränkt statt über die volle Feldhöhe zu streuen, halbiert den Beitrag
dieses Effekts. Das ist eine Bedienregel wie „mittig auflegen" und
„Vorderseite nach oben", keine Codeänderung.

---

## 7. Grenzen

- **Ein Artikel, eine Achse, zwölf Punkte.** Ob die Steigung für kürzere
  Objekte, andere Klassen oder die x-Richtung gleich ausfällt, ist offen. Die
  x-Spanne der Leiter beträgt nur 7,7 mm — über x sagt diese Serie nichts.
- **Der Mechanismus ist nicht bestimmt.** Keystone, schräge Sicht auf ein
  Objekt mit Höhe und positionsabhängige Kantenlage der Segmentierung erzeugen
  alle einen Gradienten. Die Anisotropie (Breite fällt 2,66× schneller)
  spricht gegen einen reinen Maßstabsfehler, benennt aber keine Ursache.
- **Der Betriebs-Floor bleibt geschätzt**, nicht gemessen. Gemessen ist eine
  Steigung; der Floor folgt erst aus der tatsächlichen Auflage-Streuung.
- Die Serie stammt vom Mac-Rig **ohne Fokus-Lock**. Ein Fokusunterschied über
  die Serie würde ebenfalls als Maßstabsänderung erscheinen — die
  Zeit-Kontrolle in Abschnitt 4 schließt eine *monotone* Fokusdrift aus, nicht
  aber eine positionsabhängige Nachführung durch den Autofokus.

### Was den Befund entscheidbar machen würde

Ein **Raster statt einer Linie**: dasselbe Objekt an 5 × 3 Positionen über das
Feld, je 2–3 Aufnahmen. Daraus fällt sofort ab, ob der Gradient linear ist
(Keystone), radialsymmetrisch (Verzeichnung) oder keins von beidem, und ob x
und y verschiedene Steigungen haben. Das ist eine halbe Stunde an der
Windows-Box und beantwortet zugleich die Floor-Frage, an der w(s), D7 und D8
hängen. Es gehört damit in dieselbe Session wie das Komplett-Neu-Enrollment.

---

## Verwandte Dokumente

- [2026-07-27-scoring-analyse.md](2026-07-27-scoring-analyse.md), Abschnitte 5
  und 9 — der Orientierungs-Test, dessen Nullbefund hier eingeordnet wird.
- [2026-08-01-wprofil-negativbefund.md](2026-08-01-wprofil-negativbefund.md),
  Abschnitt 6 und Nachtrag 11 — die Floor-Abschätzung, die auf dieser Messung
  beruht, und die 1,0-mm-Grenze.
- [2026-08-01-fixpunkt-test-scoring.md](2026-08-01-fixpunkt-test-scoring.md) —
  der Test, der den Positionsanteil per Fixpunkt eliminiert hat; diese Messung
  ist seine Prämisse.
- [2026-07-31-ablauf-enrollment-session.md](2026-07-31-ablauf-enrollment-session.md) —
  die Pflicht zur verteilten Auflage, die daraus folgt.
- [superpowers/reports/2026-07-24-stammdaten-sync-ergebnis.md](superpowers/reports/2026-07-24-stammdaten-sync-ergebnis.md),
  Abschnitt 6b — die ~1,3-%-Skalen-Drift zwischen Sessions. Gleiche
  Größenordnung, andere Achse (Zeit statt Ort); ob beides zusammenhängt, ist
  offen.
