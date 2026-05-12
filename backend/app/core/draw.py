"""
Cryptographically secure draw.

Uses the secrets module (OS entropy pool, equivalent to
window.crypto.getRandomValues in the browser MVP).

secrets.randbelow(n) implements rejection sampling internally,
so there is no modulo bias. The shuffle is a partial Fisher-Yates.
"""

import secrets


def secure_draw(pool: list[dict], num_winners: int) -> list[dict]:
    """
    Draw num_winners entries from pool without replacement.

    Raises ValueError if num_winners > len(pool).
    """
    if num_winners > len(pool):
        raise ValueError(
            f"Cannot draw {num_winners} winners from a pool of {len(pool)}."
        )
    if num_winners == len(pool):
        return list(pool)

    pool = list(pool)
    for i in range(num_winners):
        j = i + secrets.randbelow(len(pool) - i)
        pool[i], pool[j] = pool[j], pool[i]

    return pool[:num_winners]
