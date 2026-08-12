"""Hilfe-System der Qt-UI (Ebene 1 kontextsensitiv + Ebene 2 Hilfeseite).

Qt-freier Kern (anker.py, texte.py) und Qt-Fenster (fenster.py). Die
Texte liegen als Markdown-Paketdaten unter hilfe/<sprache>/ und werden
über importlib.resources geladen — nie über CWD-relative Pfade.
"""
