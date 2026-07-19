"""Native Desktop-UI (PySide6) für die Fotobox – Bediener-Oberfläche.

Start: python -m docodetect.ui_qt [--demo] [--config PFAD]

Architektur-Invarianten (PLAN_UI_QT.md, Abschnitt 1):
- UI-Code ruft ausschließlich docodetect.pipeline auf (+ Qt, cv2 fürs
  Konvertieren). Keine direkten Imports von database/matcher/segmentation.
- Alle Parameter aus config/config.yaml (ui:-Sektion, Fallbacks in app.ui_cfg).
- Kein Pipeline-/Kamera-Aufruf im GUI-Thread (camera_worker/pipeline_worker).
"""
