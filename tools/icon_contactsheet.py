#!/usr/bin/env python3
"""Kontaktbogen aller Strichicons über Größen × devicePixelRatio.

Rendert JEDES in ``icons.NAMES`` definierte Icon in allen im UI verwendeten
Kantenlängen (18/20/24 px) und für dpr 1/2/3, jede Zelle mit einem roten
Bounding-Box-Rahmen exakt um das physische Icon-Rect – so fällt ein Anschnitt
(Crop) sofort auf.

Läuft headless::

    QT_QPA_PLATFORM=offscreen python tools/icon_contactsheet.py

Schreibt ``reports/icon_contactsheet.png`` und gibt den Pfad aus.

WICHTIG: Vor dem Compositing wird die devicePixelRatio jeder Einzel-Pixmap
auf 1 gesetzt. Sonst zeichnet Qt sie beim ``drawPixmap`` auf die Sheet-Canvas
wieder LOGISCH herunter (Backing/dpr) und ein Crop bliebe unsichtbar – wir
wollen die rohen physischen Pixel sehen.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRectF, Qt                       # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

from docodetect.ui_qt import icons                          # noqa: E402

SIZES = (18, 20, 24)          # alle im UI genutzten Icon-Kantenlängen
# macOS: 1/2/3 (+ Zoomstufen 1.5/2.5). Windows: 125 % = 1.25, 175 % = 1.75 –
# krumme size*dpr (18·1.25=22.5), also der ceil-Fall.
DPRS = (1, 1.25, 1.5, 1.75, 2, 2.5, 3)
ICON_COLOR = "#111111"
BG = "#f4f4f5"
FRAME = "#d81f2a"             # roter Rahmen = physisches Icon-Rect
TEXT = "#3a3a3a"

CELL_PAD = 16
MAX_PHYS = max(SIZES) * max(DPRS)      # 72 px = größtes physisches Icon
CELL = MAX_PHYS + 2 * CELL_PAD
COL_LABEL_H = 28
ROW_LABEL_W = 74


def build() -> Path:
    cols = [(s, d) for s in SIZES for d in DPRS]
    names = list(icons.NAMES)
    width = ROW_LABEL_W + len(cols) * CELL
    height = COL_LABEL_H + len(names) * CELL

    sheet = QImage(width, height, QImage.Format_ARGB32)
    sheet.fill(QColor(BG))
    p = QPainter(sheet)
    p.setRenderHint(QPainter.Antialiasing, True)

    header = QFont()
    header.setPointSize(8)
    p.setFont(header)

    # Spaltenüberschriften (Größe @ dpr)
    p.setPen(QColor(TEXT))
    for c, (s, d) in enumerate(cols):
        x = ROW_LABEL_W + c * CELL
        p.drawText(QRectF(x, 0, CELL, COL_LABEL_H),
                   int(Qt.AlignCenter), f"{s}px @{d}x")

    for r, name in enumerate(names):
        y0 = COL_LABEL_H + r * CELL
        p.setPen(QColor(TEXT))
        p.drawText(QRectF(0, y0, ROW_LABEL_W, CELL),
                   int(Qt.AlignCenter), name)
        for c, (s, d) in enumerate(cols):
            x0 = ROW_LABEL_W + c * CELL
            px = icons.pixmap(name, s, ICON_COLOR, float(d))
            phys = px.width()                 # physische Pixel (= Backing)
            px.setDevicePixelRatio(1.0)       # rohe Pixel zeigen, nicht logisch
            dx = x0 + (CELL - phys) / 2.0
            dy = y0 + (CELL - phys) / 2.0
            p.setPen(QPen(QColor(FRAME), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(dx - 0.5, dy - 0.5, phys + 1, phys + 1))
            p.drawPixmap(int(round(dx)), int(round(dy)), px)

    p.end()
    out = Path(__file__).resolve().parents[1] / "reports" / "icon_contactsheet.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(str(out))
    return out


def main() -> None:
    QApplication.instance() or QApplication(sys.argv)
    print(build())


if __name__ == "__main__":
    main()
