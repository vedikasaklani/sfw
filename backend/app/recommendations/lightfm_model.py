"""LightFM hybrid scorer. The only module that imports LightFM.

Input is already contract-shaped (book ids, feature keys, weighted reading events), so this file
never sees Koha data. Swap or tune the model here without touching ranking/explanations.
"""
from dataclasses import dataclass

try:  # optional extra: ./scripts/install_lightfm.sh (needs a C compiler)
    import numpy as np
    from lightfm import LightFM
    from lightfm.data import Dataset
    AVAILABLE = True
    IMPORT_ERROR = ""
except ImportError as exc:  # pragma: no cover - depends on the environment
    AVAILABLE = False
    IMPORT_ERROR = str(exc)


@dataclass(frozen=True)
class ModelConfig:
    loss: str = "warp"          # warp suits implicit "borrowed it" feedback
    no_components: int = 16
    learning_rate: float = 0.05
    epochs: int = 40
    random_state: int = 42      # fixed so the same snapshot ranks the same way
    num_threads: int = 1


DEFAULT_CONFIG = ModelConfig()


def score(item_ids: list[str], item_features: dict[str, list[str]], events: list[tuple[str, float]], config: ModelConfig = DEFAULT_CONFIG) -> dict[str, float]:
    """Fit a one-reader hybrid model and return item_id -> score scaled to 0..1.

    Item embeddings are built from shared metadata features (plus per-item identity), so the
    learned reader vector generalises to unread books sharing authors/subjects/series.
    events: (item_id, weight) pairs for books the reader borrowed; unknown ids are ignored.
    """
    if not AVAILABLE:
        raise RuntimeError(f"LightFM is not installed: {IMPORT_ERROR}")
    known = set(item_ids)
    events = [(i, w) for i, w in events if i in known and w > 0]
    if not item_ids or not events:
        return {}
    dataset = Dataset()
    dataset.fit(users=["reader"], items=item_ids, item_features=sorted({f for fs in item_features.values() for f in fs}))
    interactions, weights = dataset.build_interactions(("reader", i, w) for i, w in events)
    features = dataset.build_item_features((i, item_features.get(i, [])) for i in item_ids)
    model = LightFM(loss=config.loss, no_components=config.no_components, learning_rate=config.learning_rate, random_state=config.random_state)
    model.fit(interactions, sample_weight=weights, item_features=features, epochs=config.epochs, num_threads=config.num_threads)
    _, _, item_map, _ = dataset.mapping()
    raw = model.predict(0, np.array([item_map[i] for i in item_ids], dtype=np.int32), item_features=features, num_threads=config.num_threads)
    lo, hi = float(raw.min()), float(raw.max())
    return {i: (float(s) - lo) / (hi - lo) if hi > lo else 0.0 for i, s in zip(item_ids, raw)}
