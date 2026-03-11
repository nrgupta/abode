import asyncio
import json
import os
import re

import anthropic

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def deduplicate_listings(listings: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for listing in listings:
        key = (listing.get("url") or listing.get("title") or "").lower().strip()
        if key in seen:
            continue
        seen.add(key)
        unique.append(listing)
    return unique


def analyze_listing(listing: dict) -> dict:
    prompt = f"""You are a smart apartment-hunting assistant helping someone find a great apartment in Chicago.

Analyze this listing and respond ONLY with a JSON object (no markdown, no extra text):

Listing:
- Title: {listing.get('title')}
- Price: {listing.get('price')}
- Location: {listing.get('location')}
- Source: {listing.get('source')}
- URL: {listing.get('url')}
- Beds: {listing.get('beds') or 'unknown'}
- Baths: {listing.get('baths') or 'unknown'}
- Sqft: {listing.get('sqft') or 'unknown'}

Filters:
- Max Rent: ${config.search['maxRent']}/mo
- Bedrooms: {config.search['bedrooms']}
- Preferred neighborhoods: {', '.join(config.preferred_neighborhoods)}
- Bonus keywords: {', '.join(config.bonus_keywords)}
- Red flag keywords: {', '.join(config.red_flag_keywords)}

Return ONLY this JSON:
{{
  "score": <number 1-10>,
  "summary": "<2-3 sentence summary>",
  "bonusFlags": ["<bonus keywords found>"],
  "redFlags": ["<red flag keywords found>"],
  "neighborhoodMatch": <true/false>,
  "withinBudget": <true/false>
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        text = re.sub(r"```json|```", "", text).strip()
        parsed = json.loads(text)
        return {**listing, **parsed}
    except Exception as e:
        print(f"\nAgent error for \"{listing.get('title')}\": {e}")
        return {
            **listing,
            "score": 5,
            "summary": "Could not analyze.",
            "bonusFlags": [],
            "redFlags": [],
            "neighborhoodMatch": False,
            "withinBudget": True,
        }


async def run_agent(raw_listings: list[dict]) -> list[dict]:
    print(f"\nAgent received {len(raw_listings)} raw listings")
    unique = deduplicate_listings(raw_listings)
    print(f"After deduplication: {len(unique)} listings")

    analyzed = []
    for listing in unique:
        title_preview = (listing.get("title") or "")[:50]
        print(f"   Analyzing: {title_preview}...", end="", flush=True)
        result = analyze_listing(listing)
        analyzed.append(result)
        print(f" score: {result.get('score')}/10")
        await asyncio.sleep(0.5)

    analyzed.sort(key=lambda x: x.get("score", 0), reverse=True)
    return analyzed
