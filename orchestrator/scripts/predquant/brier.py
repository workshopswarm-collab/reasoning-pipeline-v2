import math
from typing import Optional


LOG_LOSS_EPSILON = 1e-15


def as_float(value):
    if value in (None, ""):
        return None
    return float(value)


def validate_probability(value, field_name: str) -> float:
    probability = as_float(value)
    if probability is None or not 0.0 <= probability <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return probability


def brier_score(probability, outcome) -> float:
    probability = validate_probability(probability, "probability")
    outcome = validate_probability(outcome, "outcome")
    return (probability - outcome) ** 2


def brier_edge(prediction_brier, market_brier):
    if prediction_brier is None or market_brier is None:
        return None
    return float(market_brier) - float(prediction_brier)


def binary_log_loss(probability, outcome) -> float:
    probability = validate_probability(probability, "probability")
    outcome = validate_probability(outcome, "outcome")
    clipped = min(max(probability, LOG_LOSS_EPSILON), 1.0 - LOG_LOSS_EPSILON)
    return -(outcome * math.log(clipped) + (1.0 - outcome) * math.log(1.0 - clipped))


def reliability_bucket(probability, bucket_count: int = 10) -> str:
    probability = validate_probability(probability, "probability")
    if bucket_count <= 0:
        raise ValueError("bucket_count must be positive")
    bucket_index = min(bucket_count - 1, int(probability * bucket_count))
    lower = int(100 * bucket_index / bucket_count)
    upper = int(100 * (bucket_index + 1) / bucket_count)
    return f"p{lower:02d}_{upper:02d}" if upper < 100 else f"p{lower:02d}_100"


def probability_or_none(value):
    try:
        probability = as_float(value)
    except (TypeError, ValueError):
        return None
    if probability is None or not 0.0 <= probability <= 1.0:
        return None
    return probability


def snapshot_value(snapshot, key: str):
    if snapshot is None:
        return None
    if hasattr(snapshot, "keys") and key in snapshot.keys():
        return snapshot[key]
    if hasattr(snapshot, "get"):
        return snapshot.get(key)
    try:
        return snapshot[key]
    except (KeyError, TypeError, IndexError):
        return None


def market_probability_from_snapshot(
    snapshot,
    current_price=None,
) -> tuple[Optional[float], Optional[str]]:
    best_bid = probability_or_none(snapshot_value(snapshot, "best_bid"))
    best_ask = probability_or_none(snapshot_value(snapshot, "best_ask"))
    if best_bid is not None and best_ask is not None:
        return (best_bid + best_ask) / 2.0, "bid_ask_midpoint"

    yes_price = probability_or_none(snapshot_value(snapshot, "yes_price"))
    if yes_price is not None:
        return yes_price, "yes_price"

    last_price = probability_or_none(snapshot_value(snapshot, "last_price"))
    if last_price is not None:
        return last_price, "last_price"

    current_price = probability_or_none(current_price)
    if current_price is not None:
        return current_price, "current_price"

    return None, None


def prediction_scores(predicted_probability, market_probability, outcome) -> dict:
    predicted_probability = validate_probability(
        predicted_probability,
        "predicted_probability",
    )
    outcome = validate_probability(outcome, "outcome")
    market_brier = None
    if market_probability is not None:
        market_brier = brier_score(market_probability, outcome)
    return {
        "prediction_brier": brier_score(predicted_probability, outcome),
        "market_brier": market_brier,
    }
