from __future__ import annotations
from typing import Optional, Tuple

def classify(metric: str, actual: int, target: Optional[int]) -> tuple[str, Optional[float]]:
    """
    Категоризация факт vs цель.
    - indicators_done, stages_done: больше — лучше.
      good: >=100%, average: 70-99%, bad: <70%. (target=0 → actual>0 good, иначе bad)
    - penalty_sum: меньше — лучше.
      good: actual <= target, average: <=130% target, bad: >130% target.
      (target=0 → actual=0 good, иначе bad)
    """
    if target is None:
        return "no_target", None
    tgt = max(target, 0)
    if metric == "penalty_sum":
        if tgt == 0:
            return ("good" if actual == 0 else "bad"), None
        ratio = actual / tgt
        if actual <= tgt:          return "good", ratio
        if actual <= tgt * 1.3:    return "average", ratio
        return "bad", ratio
    # higher-is-better
    if tgt == 0:
        return ("good" if actual > 0 else "bad"), None
    ratio = actual / tgt
    if ratio >= 1.0: return "good", ratio
    if ratio >= 0.7: return "average", ratio
    return "bad", ratio
