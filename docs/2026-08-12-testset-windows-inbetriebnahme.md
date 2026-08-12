# Real-Capture-Testset: Inbetriebnahme an der Windows-Box

**Gehört zur Windows-Sitzung neben Vormerkliste 23, 25 und 28.**
Zweck: echte Aufnahmen samt Aufnahmezustand einfrieren, damit sie beliebig
oft reproduzierbar durchgerechnet werden können. Der Bestand startet an der
Box bei null — nichts vom Mac wird übernommen. Das Replay ist **rein
berichtend**, kein Gate; Tier 1/2 des Korpus bleiben unverändert Merge-Gate.

## Einmalig einrichten

1. `config/config.local.yaml` an der Box (nur Maschinen-Spezifisches):

   ```yaml
   paths:
     testset_dir: D:/Doco_Detect_testset   # AUSSERHALB des Repos, wie der Korpus
   ```

   Ohne Eintrag gilt `../Doco_Detect_testset` neben dem Projektordner —
   das ist auch in Ordnung; wichtig ist nur: außerhalb von Git.
2. Prüfen, dass `paths.save_captures` **nicht** auf `false` steht
   (Default `true`): ohne gespeichertes PNG kann der Builder nichts
   einfrieren, die Reports zählen dann als `ohne_bild`.
3. Windows-venv-Eigenheiten wie immer: `.venv\Scripts\Activate.ps1`,
   `python -m pip`.

## Laufender Betrieb (die Reihenfolge ist der Punkt)

1. **Aufnehmen** wie gewohnt (Qt-UI, Identifizieren). Jede Aufnahme landet
   als PNG + Report-JSON mit `zustand`-Block in `data/captures/`.
2. **Bewerten** in der UI (Richtig / Falsch mit wahrem Artikel / zu Recht
   abgelehnt). Unbewertetes und „Falsch" ohne Artikel nimmt der Builder
   nicht — er zählt es nur.
3. **`python -m docodetect.cli testset-build`** — und zwar **VOR** jeder
   Neukalibrierung, jedem Hintergrund-Neuaufbau und jedem Einlernen.
   Der Builder friert den Zustand nur ein, solange er noch der lebende ist;
   ist er schon weitergezogen, meldet er
   `zustand_nicht_mehr_vorhanden` und die Aufnahmen sind fürs Testset
   verloren (bewusst: rekonstruiert wird nie).
   Faustregel: **Bewertungsrunde abgeschlossen → sofort bauen.**
4. Befunde des Builders lesen. `BEFUND:`-Zeilen (Widersprüche, unbekannte
   Labels, Fidelity-Abweichungen) sind der Zweck des Werkzeugs — sie werden
   gemeldet, nie automatisch aufgelöst.
5. **`python -m docodetect.cli testset-replay`** nach Bedarf: rechnet alle
   Bündel durch, legt `runs/<id>/results.json|metrics.json|lauf.json` ab
   (zwei Läufe auf gleichem Stand sind byteidentisch, also diffbar).
   `false_accept` muss 0 bleiben — steht dort etwas anderes, ist das ein
   Befund erster Ordnung.
   **Exit-Codes:** `0` = alles reproduziert, keine Befunde. `1` = Befund —
   Abweichung, Bündel-Fehler oder `false_accept > 0` (dann zusätzlich die
   Zeile `INVARIANTE VERLETZT`). Exit 1 ist **kein Absturz der Harness**,
   sondern genau das Signal, für das sie existiert; die Ursache steht in
   den `ABWEICHUNG`/`FEHLER`-Zeilen darüber.
6. `testset/manifest.json` (im Repo) committen wie `corpus/manifest.json` —
   Commit-Message an der Box über Datei (`git commit -F <datei>`), nie
   inline.

## Was die Meldungen bedeuten

- **`PLATTFORM: … NICHT vergleichbar`** — der Lauf rechnet auf einer
  anderen Plattform/Bibliothek als der Aufnahmezustand (z.B. Mac gegen
  Windows-Bündel). Strukturprüfung ja, Zahlenvergleich nein. Keine Toleranz
  erfinden — das ist der dokumentierte H-S-Drift.
- **`FEHLER … Buendel: unvollstaendig/weicht ab`** — Snapshot beschädigt
  oder unvollständig; alle Aufnahmen des Bündels sind Fehler, kein
  stiller Teil-Lauf. Ursache klären, nicht überspielen.
- **`ABWEICHUNG`** — gleiche Pixel, gleicher Zustand, anderes Ergebnis:
  das ist genau das Signal, für das die Harness existiert (Code- oder
  Bibliotheksänderung). Mit `corpus-run` gegenprüfen und als Befund
  behandeln.

## Abgrenzung

- Bestehende Captures aus `data/captures/` (Mac-Bestände, 26 Qt-JPGs)
  werden **nicht** eingelesen — keine Rückwirkend-Verarbeitung.
- **Reports aus der Zeit vor der PNG/zustand-Umstellung (2026-08-12) sind
  nicht replaybar — bekannt, kein Fehler des Builders.** Er überspringt
  sie mit eigenem, benanntem Zähler und BEFUND-Zeile je Datei:
  `ohne_zustand` (Report ohne `zustand`-Block, der tiefere Grund greift
  zuerst) bzw. `kein_png` (verlustbehaftetes Capture, praktisch die
  Qt-Ära-JPGs — docs/2026-08-12-qt-captures-jpg-verlustbehaftet.md).
- `testset-build`/`testset-replay` sind unter `--sandbox` gesperrt.
- Messpfad, Segmentierung, `matching`-Block, Tier 1/2, DB-Schema: von
  diesem Werkzeug unberührt.
