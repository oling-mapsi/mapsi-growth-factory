from __future__ import annotations

import json
import logging
from collections import Counter

logger = logging.getLogger("app.github")
metrics_counter: Counter[str] = Counter()


def incr(metric_name: str, value: int = 1) -> None:
    metrics_counter[metric_name] += value


def structured_log(event: str, **payload: object) -> None:
    logger.info(json.dumps({"event": event, **payload}, sort_keys=True, default=str))
