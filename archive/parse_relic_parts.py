import re
import json

# Read the HTML file from the working directory
with open("input.html", "r", encoding="utf-8") as f:
    html_content = f.read()

def parse_rows(html_content):
    """Parse the wiki HTML to extract relic -> parts mapping."""
    mapping = {}
    
    # Pattern matches rows with part name link, part type, and relic tooltip
    row_pattern = re.compile(
        r'<tr>\s*'
        r'<td[^>]*>(?:\n|\r)*'  # Start of first td (part name)
        r'<a\s+href="/w/([^/]+)"[^>]*>'  # Part slug from href
        r'(.*?)</a>'  # Part name text
        r'</td>\s*'
        r'<td[^>]*>(.*?)</td>\s*'  # Part type (Blueprint, Barrel, etc.)
        r'<td[^>]*><span\s+class="tooltip[^"]*" data-param-name="([^"]+)"[^>]*>'  # Relic name from data-param-name
        r'.*?</span></td>'
        r'(?:\n|\r)*</tr>',
        re.DOTALL | re.IGNORECASE
    )
    
    for match in row_pattern.finditer(html_content):
        part_slug = match.group(1)
        part_name_raw = match.group(2).strip()
        part_type = match.group(3).strip().lower()
        relic_name = match.group(4)
        
        # Build full slug: Part_Name_Type (e.g., "Larkspur_Prime_Barrel")
        slugify_part_name = "".join(c for c in part_name_raw.replace(" ", "_").replace("-", "_").lower())
        full_slug = f"{slugify_part_name}_{part_type}"
        
        # Normalize relic name key
        relic_key = re.sub(r'[ _\-]', ' ', relic_name.lower()).strip()
        if relic_key.endswith('relic'):
            relic_key = relic_key[:-6].strip()
        
        if relic_key not in mapping:
            mapping[relic_key] = []
        
        # Add part to mapping (avoid duplicates)
        if full_slug not in mapping[relic_key]:
            mapping[relic_key].append(full_slug)
    
    return mapping

print("Parsing rows...")
mapping = parse_rows(html_content)
print(f"Found {len(mapping)} unique relics with parts")

# Print some examples
print("\nFirst 10 relics:")
for key, parts in list(mapping.items())[:10]:
    print(f"  {key}: {parts}")

# Save the mapping to a JSON file for use by the Python script
with open("relic_parts_mapping.json", "w", encoding="utf-8") as f:
    json.dump({k: parts for k, parts in mapping.items()}, f, indent=2)

print(f"\nMapping saved to relic_parts_mapping.json with {len(mapping)} relics")

# Also print total number of part entries
total_parts = sum(len(parts) for parts in mapping.values())
print(f"Total part entries: {total_parts}")