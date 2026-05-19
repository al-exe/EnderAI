from app.core.metrics import REGISTRY, all_metric_names, rollup_metric_names
from app.core.metrics.registry import metric


def test_registry_contains_headline_metrics() -> None:
    for name in (
        "tokens_saved",
        "usd_saved",
        "tokens_consumed",
        "usd_consumed",
        "documents_touched",
        "reuse_rate",
    ):
        assert name in REGISTRY


def test_rollup_metric_names_excludes_composed() -> None:
    rollup = set(rollup_metric_names())
    assert "documents_touched" not in rollup
    assert "reuse_rate" not in rollup
    assert "tokens_saved" in rollup
    assert "tokens_consumed" in rollup


def test_metric_lookup_returns_definition() -> None:
    defn = metric("tokens_saved")
    assert defn.unit == "tokens"
    assert defn.presentation.format == "compact-int"
    assert defn.presentation.icon == "spark"


def test_all_metric_names_is_stable_order() -> None:
    names = all_metric_names()
    # First call same as second call — order should be deterministic.
    assert names == all_metric_names()
    assert len(names) == len(set(names))
