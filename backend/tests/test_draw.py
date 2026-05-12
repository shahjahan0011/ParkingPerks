"""Tests for the cryptographic draw."""

import pytest
from collections import Counter

from app.core.draw import secure_draw


def _pool(n: int) -> list[dict]:
    return [{"plate": f"PLATE{i:04d}"} for i in range(n)]


class TestSecureDraw:
    def test_returns_correct_count(self):
        assert len(secure_draw(_pool(50), 3)) == 3

    def test_no_duplicates(self):
        winners = secure_draw(_pool(50), 10)
        plates = [w["plate"] for w in winners]
        assert len(plates) == len(set(plates))

    def test_full_pool_draw(self):
        pool = _pool(5)
        winners = secure_draw(pool, 5)
        assert len(winners) == 5

    def test_cannot_overdraw(self):
        with pytest.raises(ValueError):
            secure_draw(_pool(3), 5)

    def test_does_not_mutate_original_pool(self):
        pool = _pool(10)
        original_plates = [p["plate"] for p in pool]
        secure_draw(pool, 3)
        assert [p["plate"] for p in pool] == original_plates

    def test_single_winner_draw(self):
        pool = _pool(100)
        winners = secure_draw(pool, 1)
        assert len(winners) == 1
        assert winners[0] in pool

    def test_statistical_uniformity(self):
        """
        100 000 draws from a pool of 5 — chi-squared sanity check.
        Each entry should win ~20 000 times. We allow ±5% tolerance
        (1000 draws), which is extremely conservative for 100 k trials.
        """
        pool = _pool(5)
        counts: Counter = Counter()
        for _ in range(100_000):
            winner = secure_draw(pool, 1)[0]
            counts[winner["plate"]] += 1

        expected = 100_000 / 5
        for plate, count in counts.items():
            assert abs(count - expected) < 1_000, (
                f"{plate} won {count} times (expected ~{expected:.0f})"
            )
