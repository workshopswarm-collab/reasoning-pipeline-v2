import argparse
import json
import re
import sys
import warnings
from datetime import datetime, timedelta, timezone


# --- Configuration & API ---

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
OUTPUT_FILE = "filtered_markets.json"

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL.*")


# --- Filtering Criteria ---

MIN_VOLUME = 10000.0
MAX_VOLUME = 150000000.0
MIN_LIQUIDITY = 3000.0
MIN_YES_PROBABILITY = 0.10
MAX_YES_PROBABILITY = 0.95


# --- Category normalization ---

CATEGORY_NORMALIZATION_VERSION = "polymarket-high-level-v1"
UNKNOWN_CATEGORY = "unknown"
NOISE_TAG_SLUGS = {
    "all",
    "breaking-news",
    "earn-4",
    "featured",
    "hide-from-new",
    "recurring",
    "weekly",
    "yearly",
}

SPORTS_TAG_SLUGS = {
    "sports",
    "games",
    "soccer",
    "basketball",
    "nba",
    "wnba",
    "nfl",
    "mlb",
    "nhl",
    "tennis",
    "golf",
    "mma",
    "ufc",
    "ncaa",
    "ncaa-football",
    "ncaa-basketball",
    "epl",
    "la-liga",
    "bundesliga",
    "baseball",
    "hockey",
    "fide",
    "chess",
    "cricket",
    "rugby",
    "formula-1",
    "f1",
    "motorsport",
}

CRYPTO_TAG_SLUGS = {
    "crypto",
    "crypto-prices",
    "bitcoin",
    "ethereum",
    "solana",
    "dogecoin",
    "exchange",
    "token-launch",
    "pre-market",
    "airdrops",
    "fdv",
    "microstrategy",
    "xrp",
    "binance",
    "coinbase",
}

CATEGORY_TAG_RULES = [
    ("sports", SPORTS_TAG_SLUGS),
    ("crypto", CRYPTO_TAG_SLUGS),
    (
        "tech_ai",
        {
            "tech",
            "big-tech",
            "ai",
            "openai",
            "anthropic",
            "google",
            "microsoft",
            "nvidia",
            "meta",
            "apple",
            "tesla",
            "spacex",
            "grok",
            "sam-altman",
            "gpt-5",
        },
    ),
    (
        "science_health_weather",
        {
            "science",
            "health",
            "weather",
            "climate",
            "hurricane",
            "earthquake",
            "space",
            "biotech",
            "public-health",
        },
    ),
    (
        "culture_entertainment",
        {
            "pop-culture",
            "culture",
            "celebrities",
            "movies",
            "music",
            "awards",
            "gaming",
            "gta-vi",
        },
    ),
    (
        "business_finance_macro",
        {
            "finance",
            "business",
            "economy",
            "economic-policy",
            "fed-rates",
            "global-rates",
            "interest-rates",
            "ipo",
            "ipos",
            "stocks",
            "taxes",
            "fed",
            "inflation",
            "recession",
        },
    ),
    (
        "geopolitics_world",
        {
            "geopolitics",
            "world-affairs",
            "foreign-policy",
            "ukraine",
            "russia",
            "israel",
            "gaza",
            "iran",
            "china",
            "nato",
            "middle-east",
            "south-korea",
            "syria",
            "taiwan",
            "eu",
            "putin",
            "military-action",
            "ukraine-map",
            "world-elections",
            "global-elections",
        },
    ),
    (
        "politics_elections",
        {
            "politics",
            "elections",
            "primary-elections",
            "primaries",
            "midterms",
            "us-presidential-election",
            "governor-midterms",
            "senate-midterms",
            "senate-primary",
            "house-primary",
            "democratic-primary",
            "republican-primary",
            "president",
            "presidential",
            "congress",
            "senate",
            "house",
            "mayor",
            "governor",
            "nyc-mayor",
            "referendum",
            "parliament",
        },
    ),
]

SPORTS_KEYWORDS = (
    " vs ",
    " v ",
    "tournament",
    "league",
    "cup",
    "grand prix",
    "match",
    "playoff",
    "final",
    "semi final",
    "quarterfinal",
    "quarter final",
    "nba",
    "wnba",
    "nfl",
    "mlb",
    "nhl",
    "ufc",
    "fifa",
    "uefa",
    "fide",
    "chess",
    "tennis",
    "soccer",
    "baseball",
    "basketball",
    "hockey",
    "cricket",
    "rugby",
    "formula 1",
    "f1",
)

CRYPTO_ASSET_KEYWORDS = (
    "bitcoin",
    "btc",
    "ethereum",
    "eth",
    "solana",
    "sol",
    "xrp",
    "dogecoin",
    "doge",
    "litecoin",
    "ltc",
    "cardano",
    "ada",
    "avalanche",
    "avax",
    "polkadot",
    "dot",
    "ripple",
    "binance coin",
    "bnb",
    "crypto",
)

CRYPTO_PRICE_KEYWORDS = (
    "price",
    "reach",
    "hit",
    "above",
    "below",
    "over",
    "under",
    "between",
    "higher than",
    "lower than",
    "all time high",
    "ath",
    "new high",
    "market cap",
    "up or down",
    "updown",
)

CATEGORY_KEYWORD_RULES = [
    ("sports", SPORTS_KEYWORDS),
    (
        "crypto",
        (
            "bitcoin",
            "btc",
            "ethereum",
            "eth",
            "solana",
            "sol",
            "xrp",
            "dogecoin",
            "doge",
            "litecoin",
            "ltc",
            "cardano",
            "ada",
            "avalanche",
            "avax",
            "polkadot",
            "dot",
            "ripple",
            "binance",
            "coinbase",
            "microstrategy",
            "crypto",
            "token launch",
            "airdrop",
            "fdv",
            "pre market",
            "usdt",
            "usdc",
        ),
    ),
    (
        "tech_ai",
        (
            "openai",
            "chatgpt",
            "claude",
            "anthropic",
            "gemini",
            "nvidia",
            "microsoft",
            "google",
            "meta",
            "apple",
            "tesla",
            "spacex",
            "artificial intelligence",
            " ai ",
            "tech",
            "big tech",
            "grok",
            "gpt 5",
        ),
    ),
    (
        "science_health_weather",
        (
            "earthquake",
            "hurricane",
            "storm",
            "tornado",
            "volcano",
            "weather",
            "temperature",
            "rainfall",
            "climate",
            "scientific",
            "science",
            "health",
            "space",
            "biotech",
        ),
    ),
    (
        "culture_entertainment",
        (
            "culture",
            "celebrity",
            "celebrities",
            "movie",
            "movies",
            "music",
            "award",
            "awards",
            "gaming",
            "gta",
            "taylor swift",
        ),
    ),
    (
        "business_finance_macro",
        (
            "inflation",
            "cpi",
            "ppi",
            "fomc",
            "fed",
            "federal reserve",
            "interest rate",
            "rates",
            "gdp",
            "payroll",
            "jobs report",
            "unemployment",
            "recession",
            "treasury",
            "ecb",
            "ipo",
            "stocks",
            "economy",
            "business",
            "finance",
            "tax",
            "economic policy",
        ),
    ),
    (
        "geopolitics_world",
        (
            "ukraine",
            "russia",
            "israel",
            "gaza",
            "iran",
            "china",
            "taiwan",
            "ceasefire",
            "war",
            "peace deal",
            "tariff",
            "sanction",
            "geopolitics",
            "foreign policy",
            "nato",
            "middle east",
            "military clash",
        ),
    ),
    (
        "politics_elections",
        (
            "election",
            "primary",
            "senate",
            "house",
            "president",
            "presidential",
            "governor",
            "mayor",
            "parliament",
            "referendum",
            "democrat",
            "democratic",
            "republican",
            "gop",
            "trump",
            "biden",
            "macron",
            "politics",
            "congress",
            "midterm",
        ),
    ),
]


def normalize_text(value):
    if value is None:
        return ""
    text = str(value).lower()
    text = re.sub(r"[^a-z0-9$]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return f" {text} " if text else ""


def normalize_tag_slug(value):
    if isinstance(value, dict):
        value = value.get("slug") or value.get("label") or value.get("name")
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def safe_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_json_list(value, default=None):
    if default is None:
        default = []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else default
        except (json.JSONDecodeError, TypeError):
            return default
    return default


def is_yes_no_outcome_order(outcomes) -> bool:
    normalized = [str(outcome).strip().lower() for outcome in outcomes]
    return normalized[:2] == ["yes", "no"]


def infer_outcome_type(market: dict, outcomes) -> str:
    if len(outcomes) == 2 and is_yes_no_outcome_order(outcomes):
        return "binary"
    return market.get("marketType") or market.get("market_type")


def extract_tag_lists(tags):
    tags = tags or []
    tag_labels = [
        (tag.get("label") or tag.get("name") or "").strip()
        for tag in tags
        if isinstance(tag, dict) and (tag.get("label") or tag.get("name"))
    ]
    tag_slugs = [normalize_tag_slug(tag) for tag in tags if normalize_tag_slug(tag)]
    return tags, tag_labels, tag_slugs


def extract_event_tag_lists(event):
    return extract_tag_lists(event.get("tags"))


def derive_raw_category(event, tag_labels):
    raw_cat = (event.get("category") or "").strip()
    raw_sub = (event.get("subcategory") or "").strip()
    if raw_cat:
        return raw_cat, "event.category"
    if raw_sub:
        return raw_sub, "event.subcategory"
    if tag_labels:
        return ", ".join(tag_labels), "event.tags"
    return "", "fallback"


def build_candidate_tag_slugs(tag_slugs, raw_category, event, market=None):
    candidates = list(tag_slugs)

    if market:
        _, _, market_tag_slugs = extract_tag_lists(market.get("tags"))
        candidates.extend(market_tag_slugs)

    for value in (
        raw_category,
        event.get("category"),
        event.get("subcategory"),
        event.get("seriesSlug"),
        market.get("category") if market else None,
    ):
        slug = normalize_tag_slug(value)
        if slug:
            candidates.append(slug)

    deduped = []
    seen = set()
    for slug in candidates:
        if (
            not slug
            or slug in seen
            or slug in NOISE_TAG_SLUGS
            or slug in {"polymarket-discovery", "uncategorized"}
        ):
            continue
        deduped.append(slug)
        seen.add(slug)
    return deduped


def infer_category_from_tags(tag_slugs):
    tag_slug_set = set(tag_slugs)
    for category, category_tag_slugs in CATEGORY_TAG_RULES:
        if tag_slug_set.intersection(category_tag_slugs):
            return category
    return None


def infer_category_from_text(*parts):
    signal_text = " ".join(
        part for part in (normalize_text(value) for value in parts) if part
    )
    if not signal_text:
        return None
    for category, keywords in CATEGORY_KEYWORD_RULES:
        if any(normalize_text(keyword) in signal_text for keyword in keywords):
            return category
    return None


def normalize_market_category(event, market, raw_category, event_title, tag_labels, tag_slugs):
    tag_match = infer_category_from_tags(
        build_candidate_tag_slugs(tag_slugs, raw_category, event, market)
    )
    if tag_match:
        return tag_match

    text_match = infer_category_from_text(
        market.get("question"),
        event_title,
        raw_category,
        event.get("category"),
        event.get("subcategory"),
        event.get("seriesSlug"),
        market.get("slug"),
        market.get("description"),
        " ".join(tag_labels),
    )
    if text_match:
        return text_match
    return UNKNOWN_CATEGORY


def combined_market_text(event, market, raw_category, tag_labels):
    parts = (
        market.get("question"),
        market.get("slug"),
        market.get("description"),
        market.get("groupItemTitle"),
        market.get("marketType"),
        market.get("formatType"),
        event.get("title"),
        event.get("slug"),
        event.get("description"),
        event.get("category"),
        event.get("subcategory"),
        event.get("seriesSlug"),
        raw_category,
        " ".join(tag_labels),
    )
    return " ".join(normalize_text(part) for part in parts if part)


def is_sports_market(event, market, normalized_category, tag_slugs, raw_category):
    if normalized_category == "sports":
        return True

    candidate_tag_slugs = set(build_candidate_tag_slugs(tag_slugs, raw_category, event, market))
    if candidate_tag_slugs.intersection(SPORTS_TAG_SLUGS):
        return True

    sports_structural_fields = (
        "gameId",
        "game_id",
        "gameStartTime",
        "gameStatus",
        "teamAID",
        "teamBID",
        "sportsMarketType",
        "sportsMarketTypes",
    )
    if any(market.get(field) or event.get(field) for field in sports_structural_fields):
        return True

    signal_text = combined_market_text(event, market, raw_category, [])
    return any(normalize_text(keyword) in signal_text for keyword in SPORTS_KEYWORDS)


def is_crypto_price_market(event, market, tag_labels, tag_slugs, raw_category):
    candidate_tag_slugs = set(build_candidate_tag_slugs(tag_slugs, raw_category, event, market))
    if "crypto-prices" in candidate_tag_slugs:
        return True

    signal_text = combined_market_text(event, market, raw_category, tag_labels)
    has_crypto_asset = any(
        normalize_text(keyword) in signal_text for keyword in CRYPTO_ASSET_KEYWORDS
    )
    if not has_crypto_asset:
        return False

    has_price_signal = any(
        normalize_text(keyword) in signal_text for keyword in CRYPTO_PRICE_KEYWORDS
    )
    has_dollar_threshold = bool(re.search(r"\$\s?\d", signal_text))
    has_numeric_threshold = bool(
        re.search(
            r"\b(above|below|over|under|reach|hit|between)\s+\d[\d,]*(k|m)?\b",
            signal_text,
        )
    )

    return has_price_signal and (has_dollar_threshold or has_numeric_threshold)


def fetch_and_filter_all_markets(output_file=OUTPUT_FILE):
    import requests

    filtered_markets = []
    total_markets_scanned = 0
    total_markets_excluded_sports = 0
    total_markets_excluded_crypto_price = 0
    now_utc = datetime.now(timezone.utc)
    one_day_from_now = now_utc + timedelta(days=1)
    ten_days_from_now = now_utc + timedelta(days=15)

    limit = 100
    offset = 0

    print("[INFO] Initiating global sweep of Polymarket events...")

    while True:
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset,
        }

        try:
            response = requests.get(f"{GAMMA_API_BASE}/events", params=params, timeout=90)
            response.raise_for_status()
            events = response.json()

            if not events:
                break

            for event in events:
                markets = event.get("markets", [])
                event_slug = event.get("slug", "")
                event_title = event.get("title", "")
                _, tag_labels, tag_slugs = extract_event_tag_lists(event)
                raw_category, raw_category_source = derive_raw_category(event, tag_labels)

                for market in markets:
                    total_markets_scanned += 1

                    if market.get("closed") or not market.get("active", False):
                        continue

                    volume = safe_float(market.get("volume"))
                    liquidity = safe_float(market.get("liquidity"))
                    if not (MIN_VOLUME <= volume <= MAX_VOLUME) or liquidity < MIN_LIQUIDITY:
                        continue

                    outcomes_raw = parse_json_list(market.get("outcomes"), [])
                    prices_raw = parse_json_list(market.get("outcomePrices"), [0, 0])

                    try:
                        yes_price = float(prices_raw[0]) if prices_raw else 0
                    except (ValueError, TypeError, IndexError):
                        continue

                    if not (MIN_YES_PROBABILITY <= yes_price <= MAX_YES_PROBABILITY):
                        continue

                    end_date_str = market.get("endDate")
                    if not end_date_str:
                        continue

                    try:
                        end_date = datetime.fromisoformat(
                            end_date_str.replace("Z", "+00:00")
                        )
                        if not (one_day_from_now <= end_date <= ten_days_from_now):
                            continue
                    except ValueError:
                        continue

                    normalized_category = normalize_market_category(
                        event=event,
                        market=market,
                        raw_category=raw_category,
                        event_title=event_title,
                        tag_labels=tag_labels,
                        tag_slugs=tag_slugs,
                    )

                    if is_sports_market(
                        event=event,
                        market=market,
                        normalized_category=normalized_category,
                        tag_slugs=tag_slugs,
                        raw_category=raw_category,
                    ):
                        total_markets_excluded_sports += 1
                        continue

                    if is_crypto_price_market(
                        event=event,
                        market=market,
                        tag_labels=tag_labels,
                        tag_slugs=tag_slugs,
                        raw_category=raw_category,
                    ):
                        total_markets_excluded_crypto_price += 1
                        continue

                    filtered_markets.append(
                        {
                            "platform": "polymarket",
                            "external_market_id": market.get("id"),
                            "slug": market.get("slug"),
                            "title": market.get("question"),
                            "description": market.get("description"),
                            "category": normalized_category,
                            "status": "open",
                            "outcome_type": infer_outcome_type(
                                market,
                                outcomes_raw,
                            ),
                            "closes_at": market.get("endDate"),
                            "resolves_at": market.get("endDate"),
                            "metadata": {
                                "category_raw": raw_category,
                                "category_raw_source": raw_category_source,
                                "category_normalized": normalized_category,
                                "category_normalization_version": (
                                    CATEGORY_NORMALIZATION_VERSION
                                ),
                                "event_category": event.get("category"),
                                "event_subcategory": event.get("subcategory"),
                                "event_title": event_title,
                                "outcome_labels": outcomes_raw,
                                "outcome_prices": prices_raw,
                                "tag_labels": tag_labels,
                                "tag_slugs": tag_slugs,
                                "tags": tag_labels,
                            },
                            "snapshot": {
                                "last_price": safe_float(
                                    market.get("lastTradePrice"),
                                    None,
                                ),
                                "best_bid": safe_float(market.get("bestBid"), None),
                                "best_ask": safe_float(market.get("bestAsk"), None),
                                "yes_price": yes_price,
                                "no_price": round(1.0 - yes_price, 4),
                                "volume": volume,
                                "open_interest": liquidity,
                                "raw_payload": {
                                    "event_slug": event_slug,
                                    "event_id": event.get("id"),
                                    "event_title": event_title,
                                    "event_active": event.get("active"),
                                    "event_closed": event.get("closed"),
                                    "event_end_date": event.get("endDate"),
                                    "event_updated_at": event.get("updatedAt"),
                                    "market_id": market.get("id"),
                                    "market_slug": market.get("slug"),
                                    "market_active": market.get("active"),
                                    "market_closed": market.get("closed"),
                                    "market_closed_time": market.get("closedTime"),
                                    "market_end_date": market.get("endDate"),
                                    "market_start_date": market.get("startDate"),
                                    "market_updated_at": market.get("updatedAt"),
                                    "market_resolution_source": market.get(
                                        "resolutionSource"
                                    ),
                                    "market_outcomes": market.get("outcomes"),
                                    "market_outcomes_parsed": outcomes_raw,
                                    "market_outcome_prices": market.get(
                                        "outcomePrices"
                                    ),
                                    "market_outcome_prices_parsed": prices_raw,
                                    "market_accepting_orders": market.get(
                                        "acceptingOrders"
                                    ),
                                    "market_last_trade_price": market.get(
                                        "lastTradePrice"
                                    ),
                                    "market_best_bid": market.get("bestBid"),
                                    "market_best_ask": market.get("bestAsk"),
                                },
                            },
                        }
                    )

            print(
                f" -> Scanned offset {offset}..."
                f" Found {len(filtered_markets)} passing markets so far."
            )
            offset += limit

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to fetch events at offset {offset}: {e}")
            break

    total_passed = len(filtered_markets)
    print("-" * 50)
    print("[DEBUG] FILTERING FUNNEL RESULTS:")
    print(f" -> Total nested markets scanned: {total_markets_scanned}")
    print(f" -> Sports markets excluded: {total_markets_excluded_sports}")
    print(f" -> Crypto price markets excluded: {total_markets_excluded_crypto_price}")
    print(f" -> Markets passed to JSON: {total_passed}")
    print("-" * 50)

    if not filtered_markets:
        print("[CRITICAL ERROR] No markets matched the current criteria. Halting pipeline.")
        sys.exit(1)

    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(filtered_markets, f, indent=4)
        print(f"[SUCCESS] Saved output to {output_file}")
    except IOError as e:
        print(f"[ERROR] Could not write to file: {e}")

    return json.dumps(filtered_markets, indent=4)


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch and filter active Polymarket markets")
    parser.add_argument(
        "--output",
        default=OUTPUT_FILE,
        help="Path to write filtered market JSON",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fetch_and_filter_all_markets(output_file=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
