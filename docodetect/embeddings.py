"""Stage 2 (optional): visual embeddings + nearest-neighbor search.

Only needed if stage 1 leaves ambiguous candidate pairs (e.g. two plates,
same diameter, different decor detail). Uses a frozen, pretrained DINOv2 –
NO training required. Enable via config: stage2.enabled = true and install
requirements-stage2.txt.

Design: embeddings are computed on the masked, cropped object (background
removed) so the model compares dishware, not the box floor.

All heavy imports are lazy so stage 1 runs without torch installed.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .config import resolve

_EMBED_DIM = 384  # dinov2_vits14


class Stage2Error(RuntimeError):
    pass


def _lazy_imports():
    try:
        import faiss  # noqa: F401
        import torch  # noqa: F401
        import torchvision.transforms as T  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as e:
        raise Stage2Error(
            "Stage 2 dependencies missing. Install with: "
            "pip install -r requirements-stage2.txt"
        ) from e
    import faiss
    import torch
    import torchvision.transforms as T
    from PIL import Image
    return faiss, torch, T, Image


class EmbeddingIndex:
    """FAISS inner-product index over L2-normalized DINOv2 embeddings
    (= cosine similarity). Labels are article numbers."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.index_path = resolve(cfg["stage2"]["index_file"])
        self.labels_path = self.index_path.with_suffix(".labels.npy")
        self._model = None
        self._transform = None
        self._index = None
        self._labels: list[str] = []

    # ---------- model ----------

    def _load_model(self):
        faiss, torch, T, _ = _lazy_imports()
        if self._model is None:
            name = self.cfg["stage2"].get("model", "dinov2_vits14")
            self._model = torch.hub.load("facebookresearch/dinov2", name)
            self._model.eval()
            self._transform = T.Compose([
                T.Resize(256), T.CenterCrop(224), T.ToTensor(),
                T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ])

    def embed(self, image_bgr: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
        """Compute one L2-normalized embedding for a BGR image (optionally
        masked to the object and cropped to its bounding box)."""
        _, torch, _, Image = _lazy_imports()
        self._load_model()

        img = image_bgr
        if mask is not None:
            img = image_bgr.copy()
            img[mask == 0] = 0
            ys, xs = np.where(mask > 0)
            if len(xs) > 0:
                pad = 20
                y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad, img.shape[0])
                x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad, img.shape[1])
                img = img[y0:y1, x0:x1]

        pil = Image.fromarray(img[:, :, ::-1])  # BGR -> RGB
        with torch.no_grad():
            t = self._transform(pil).unsqueeze(0)
            vec = self._model(t).squeeze(0).numpy().astype("float32")
        vec /= (np.linalg.norm(vec) + 1e-9)
        return vec

    # ---------- index ----------

    def add(self, article_number: str, embedding: np.ndarray) -> None:
        faiss, *_ = _lazy_imports()
        if self._index is None:
            self._index = faiss.IndexFlatIP(_EMBED_DIM)
        self._index.add(embedding.reshape(1, -1))
        self._labels.append(article_number)

    def search(self, embedding: np.ndarray, k: int = 5) -> list[tuple[str, float]]:
        if self._index is None or self._index.ntotal == 0:
            raise Stage2Error("Embedding index is empty – enroll references first.")
        k = min(k, self._index.ntotal)
        sims, idxs = self._index.search(embedding.reshape(1, -1), k)
        return [(self._labels[i], float(s)) for s, i in zip(sims[0], idxs[0]) if i >= 0]

    def save(self) -> None:
        faiss, *_ = _lazy_imports()
        if self._index is None:
            return
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self.index_path))
        np.save(self.labels_path, np.array(self._labels))

    def load(self) -> None:
        faiss, *_ = _lazy_imports()
        if not Path(self.index_path).exists():
            raise Stage2Error(f"No index at {self.index_path}.")
        self._index = faiss.read_index(str(self.index_path))
        self._labels = list(np.load(self.labels_path))
