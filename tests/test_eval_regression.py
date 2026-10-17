"""Страж качества памяти: стенд на 200 днях «жизни» не должен тихо ухудшаться.

Быстрый режим (HashEmbedder, без модели смыслов, ~3 с). Полный режим с e5-large даёт 100%
(evals/results/baseline-e5-large.json) — его запускают вручную: python -m evals.run
"""

from evals.run import offline


def test_memory_eval_does_not_regress():
    res = offline(use_hash=True, verbose=False)
    assert res["accuracy"] >= 0.80, res["failures"]
    by = res["by_ability"]
    assert by["privacy"] == "2/2", "приватность — ноль утечек всегда"
    assert res["latency_ms_p50"] < 200
