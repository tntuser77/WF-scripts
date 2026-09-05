"""Look up part median prices from input.html (Wiki void_relic/ByRewards/SimpleTable).

Supports two input modes:
  - Relic name lookup: "neo l6" -> finds which relic uses this part, then shows the part price
  - Part name lookup: "larkspur barrel" -> looks up the part directly and shows its price

Example:
  Input: neo l6
  Output:
    Part: larkspur_prime_barrel
    market: https://warframe.market/items/larkspur_prime_barrel
    90d median avg: 36.92
    48h median avg: 38.29

  Input: Larkspur barrel
  Output:
    Part: larkspur_prime_barrel
    market: https://warframe.market/items/larkspur_prime_barrel
    90d median avg: 36.92
    48h median avg: 38.29
"""

import csv
import json
import re
import sys
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError


INPUT_HTML = Path(__file__).resolve().parent / "input.html"
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0", "Platform": "pc", "Language": "en"}


class RelicLookupError(Exception):
    pass


def normalize_value(value: str) -> str:
    """Strip whitespace and quotes from a value."""
    return value.strip().strip('"').strip("'")


def relic_match_key(name: str) -> str:
    """Normalize relic labels so 'Neo l1', 'Neo_L1_Relic', etc. compare equal."""
    text = normalize_value(name).lower().replace("_", " ")
    # Remove common suffixes
    for suffix in ['_relic', 'relic']:
        if text.endswith(suffix):
            text = text[:-len(suffix)].strip()
    return " ".join(text.split())


def parse_html_relic_parts(html_path: Path) -> dict[str, list[str]]:
    """Parse the wiki HTML to extract relic -> parts mapping.

    Returns a dict where keys are normalized relic names (e.g., "neo l1")
    and values are lists of part slugs (e.g., ["larkspur_prime_barrel"]).
    """
    if not html_path.is_file():
        raise RelicLookupError(f"Missing input file: {html_path}")

    with open(html_path, encoding="utf-8") as f:
        content = f.read()

    mapping: dict[str, list[str]] = {}

    # Pattern matches rows from the wiki table structure.
    # The table has columns: Part Name (with link), Part Type, Relic Name (tooltip)
    row_pattern = re.compile(
        r'<tr\s*>\s*'
        r'<td[^>]*>(?:\n|\r)*'  # Start of first td
        r'<a\s+href="/w/([^/]+)"[^>]*>'  # Part slug from href (e.g., "/w/larkspur_prime_barrel")
        r'(.*?)</a>'  # Part name text
        r'</td>\s*'
        r'<td[^>]*>(.*?)</td>\s*'  # Part type (Blueprint, Barrel, etc.)
        r'<td[^>]*><span\s+class="tooltip[^"]*" data-param-name="([^"]+)"[^>]*>'  # Relic name from tooltip
        r'.*?</span></td>'
        r'(?:\n|\r)*</tr>',
        re.DOTALL | re.IGNORECASE
    )

    for match in row_pattern.finditer(content):
        part_slug = match.group(1)
        part_name_raw = match.group(2).strip()
        relic_name = match.group(3)

        # Build full slug: Part_Name (e.g., "larkspur_barrel")
        clean_part = re.sub(r'[\s\-]+', '_', part_name_raw.strip())
        clean_part = clean_part.lower()
        
        # Remove common suffixes from the slug
        for suffix in ['_relic', 'relic']:
            if clean_part.endswith(suffix):
                clean_part = clean_part[:-len(suffix)].strip()

        # Determine slot type from the second column
        slot_type = match.group(2)
        part_type_matches = [
            "Blueprint", "Barrel", "Handle", "Hilt", "Receiver", 
            "Cerebrum", "Neuroptics", "Chassis"
        ]
        for pt in part_type_matches:
            if pt.lower() in slot_type.lower():
                # If this type isn't already in the slug, add it
                if not clean_part.endswith(pt.lower()):
                    full_slug = f"{clean_part}_{pt}"
                else:
                    full_slug = clean_part
                break
        else:
            full_slug = clean_part

        # Normalize relic name key
        relic_key = relic_match_key(relic_name)

        if relic_key not in mapping:
            mapping[relic_key] = []

        if full_slug not in mapping[relic_key]:
            mapping[relic_key].append(full_slug)

    return mapping


def build_reverse_mapping(part_to_relics: dict[str, list[str]]) -> dict[str, list[str]]:
    """Build reverse mapping from part slug to relic names."""
    reverse: dict[str, list[str]] = {}
    for relic_name, parts in part_to_relics.items():
        for part_slug in parts:
            if part_slug not in reverse:
                reverse[part_slug] = []
            if relic_name not in reverse[part_slug]:
                reverse[part_slug].append(relic_name)
    return reverse


def fetch_json(url: str) -> dict:
    """Fetch a JSON file from the warframe market API."""
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data


def fetch_part_statistics(part_slug: str) -> dict:
    """Get part statistics from the warframe market API.

    Returns dict with median_90d and median_48h values, plus market link.
    """
    api_url = f"https://api.warframe.market/v1/items/{part_slug}/statistics"
    market_url = f"https://warframe.market/items/{part_slug}"
    
    try:
        data = fetch_json(api_url)
        closed = data.get("payload", {}).get("statistics_closed", {})
        return {
            "market_link": market_url,
            "median_90d": average_bucket_medians(closed.get("90days", [])),
            "median_48h": average_bucket_medians(closed.get("48hours", [])),
        }
    except HTTPError as error:
        print(f"HTTP Error {error.code}: {error.reason}", file=sys.stderr)
        raise
    except URLError as error:
        print(f"URL Error: {error.reason}", file=sys.stderr)
        raise


def average_bucket_medians(buckets: list) -> float | None:
    """Average the medians from a list of bucket entries."""
    medians = [
        float(entry["median"])
        for entry in buckets
        if isinstance(entry, dict) and entry.get("median") is not None
    ]
    if not medians:
        return None
    return sum(medians) / len(medians)


def resolve_part_from_relic(relic_name: str, part_to_relics: dict[str, list[str]]) -> str | None:
    """Find which part slug(s) a relic name maps to.

    Tries exact match first, then partial/contains match.
    """
    normalized = relic_match_key(relic_name)
    
    # Try exact match
    if normalized in part_to_relics:
        parts = part_to_relics[normalized]
        if len(parts) == 1:
            return parts[0]
        else:
            joined = ", ".join(parts)
            print(f"Warning: Relic '{relic_name}' is listed under multiple parts: {joined}")

    # Try partial match (e.g., "neo l6" might be Neo L1-L9 series)
    for key, relics in part_to_relics.items():
        if key == normalized:
            continue
        # Check if any relic name contains the normalized key
        for relic in relics:
            if re.search(rf'^{re.escape(normalized)}', relic.lower(), re.IGNORECASE):
                return next(p for p in parts 
                          if re.search(rf'^{re.escape(normalized)}$', r, re.IGNORECASE))

    # Fallback: search all part slugs for the relic name
    for part_slug, relics in part_to_relics.items():
        for relic in relics:
            if normalized in relic.lower().replace("relic", "").split()[0]:
                return part_slug

    return None


def resolve_part_from_name(part_name_input: str, reverse_mapping: dict[str, list[str]]) -> str | None:
    """Try to find a part slug from a direct part name input.

    This is the key function for supporting "larkspur barrel" as input.
    Uses the reverse mapping (part_slug -> relic_names) for efficient lookup.
    """
    normalized = normalize_value(part_name_input).lower().replace(" ", "_")
    
    # Try exact match against part slugs (using reverse mapping keys)
    for slug, relics in reverse_mapping.items():
        if slug.lower() == normalized or normalized.startswith(slug.lower()) or \
           slug.startswith(normalized):
            return slug
    
    # Try substring match - check if the input appears as a substring of any relic name
    for slug, relics in reverse_mapping.items():
        for relic in relics:
            if normalized.replace(" ", "_") in relic.lower().replace("relic", ""):
                return slug

    # Fallback: try to construct a slug from the input and search for it
    cleaned = normalize_value(part_name_input).lower()
    for slug, relics in reverse_mapping.items():
        if cleaned.replace(" ", "_") == slug or slug.startswith(cleaned.replace(" ", "_")):
            return slug
    
    # Last resort: try the normalized input as-is
    slug = normalize_value(part_name_input).replace(" ", "_").lower()
    for key, parts in reverse_mapping.items():
        if slug == parts[0] or slug in [p.lower() for p in parts]:
            return slug
    
    return None


def format_price(value: float | None) -> str:
    """Format a price value."""
    return f"{value:.2f}" if value is not None else "N/A"


def lookup_relic(relic_name: str, part_to_relics: dict[str, list[str]]) -> None:
    """Lookup a relic and print its part info."""
    slug = resolve_part_from_relic(relic_name, part_to_relics)
    if not slug:
        raise RelicLookupError(f"Relic '{relic_name}' is not listed in {INPUT_HTML.name}.")

    print(f"Part: {slug}")
    
    stats = fetch_part_statistics(slug)
    print(f"  market: {stats['market_link']}")
    print(f"  90d median avg: {format_price(stats['median_90d'])}")
    print(f"  48h median avg: {format_price(stats['median_48h'])}")
    print()


def lookup_part(part_name_input: str, reverse_mapping: dict[str, list[str]]) -> None:
    """Lookup a part by name and print its relic info."""
    slug = resolve_part_from_name(part_name_input, reverse_mapping)
    if not slug:
        raise RelicLookupError(f"Part '{part_name_input}' is not listed in {INPUT_HTML.name}.")

    print(f"Part: {slug}")
    
    stats = fetch_part_statistics(slug)
    print(f"  market: {stats['market_link']}")
    print(f"  90d median avg: {format_price(stats['median_90d'])}")
    print(f"  48h median avg: {format_price(stats['median_48h'])}")

    # Show relics using this part
    relics = reverse_mapping.get(slug, [])
    
    if relics:
        print(f"\n  Relics using this part:")
        for relic in relics[:5]:  # Show first 5 relics
            print(f"    - {relic}")
        if len(relics) > 5:
            print(f"    ... and {len(relics) - 5} more")


def main() -> int:
    """Main entry point."""
    try:
        part_to_relics = parse_html_relic_parts(INPUT_HTML)
        if not part_to_relics:
            raise RelicLookupError("No relic-part mappings found in input.html.")
        
        print(f"Loaded {len(part_to_relics)} relics with parts from {INPUT_HTML.name}")

    except RelicLookupError as error:
        print(f"Error loading mapping: {error}", file=sys.stderr)
        return 1

    # Build reverse mapping for direct part lookup
    reverse_mapping = build_reverse_mapping(part_to_relics)

    names = [normalize_value(arg) for arg in sys.argv[1:] if normalize_value(arg)]
    exit_code = 0

    if names:
        for input_name in names:
            try:
                # Try as relic name first
                slug_from_relic = resolve_part_from_relic(input_name, part_to_relics)
                
                if slug_from_relic:
                    lookup_relic(input_name, part_to_relics)
                    continue
                
                # If not found as relic, try as direct part name
                slug = resolve_part_from_name(input_name, reverse_mapping)
                
                if slug:
                    lookup_part(input_name, reverse_mapping)
                else:
                    raise RelicLookupError(
                        f"Could not find '{input_name}' in {INPUT_HTML.name}. "
                        "Try a relic name (e.g., 'neo l6') or part name (e.g., 'larkspur barrel')."
                    )
            except RelicLookupError as error:
                print(f"Error: {error}", file=sys.stderr)
                exit_code = 1
            except HTTPError as error:
                print(f"HTTP Error {error.code}: {error.reason}", file=sys.stderr)
                exit_code = 1
            except URLError as error:
                print(f"URL Error: {error.reason}", file=sys.stderr)
                exit_code = 1
    
    return exit_code


if __name__ == "__main__":
    import sys
    sys.exit(main())
