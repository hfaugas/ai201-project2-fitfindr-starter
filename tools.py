"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
    _loose: bool = False,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.
        _loose:      Internal flag. When True, requires only 1 keyword match
                     instead of >50%. Used by run_agent for fallback retries.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform
    """
    listings = load_listings()

    # Step 1: filter by price
    if max_price is not None:
        listings = [l for l in listings if l["price"] <= max_price]

    # Step 2: filter by size (case-insensitive substring match)
    if size is not None:
        size_lower = size.lower()
        listings = [
            l for l in listings
            if size_lower in l["size"].lower() or l["size"].lower() in size_lower
        ]

    # Step 3: split query keywords into color words and content words.
    # Color words (e.g. "black", "red") should only match against the item's
    # `colors` field — not the title text — so "black" in "black combat boots"
    # doesn't match a flannel titled "Plaid Red/Black".
    _COLORS = {
        "black", "white", "red", "blue", "green", "yellow", "orange", "purple",
        "pink", "brown", "grey", "gray", "navy", "beige", "cream", "ivory",
        "tan", "khaki", "olive", "rust", "burgundy", "teal", "gold", "silver",
        "rose", "indigo", "maroon", "charcoal", "forest", "sage", "coral",
        "faded", "washed", "dusty", "mint", "lavender", "pastel",
    }
    all_kw = set(re.findall(r"[a-z0-9]+", description.lower()))
    color_kw = all_kw & _COLORS
    content_kw = all_kw - _COLORS

    def score(listing, full_text=True):
        # Content score: non-color keywords matched against title, category, tags
        parts = [
            listing["title"],
            listing["category"],
            " ".join(listing["style_tags"]),
            listing.get("brand") or "",
        ]
        if full_text:
            parts.append(listing["description"])
        text_words = set(re.findall(r"[a-z0-9]+", " ".join(parts).lower()))

        if content_kw:
            content_score = len(content_kw & text_words)
        else:
            # Query is color-only (e.g. "black") — fall back to matching all
            # keywords across the full text so single-word color queries still work
            content_score = len(all_kw & text_words)

        # Color bonus: each matching color adds 0.5 to sort score (not to threshold)
        item_colors = {c.lower() for c in listing.get("colors", [])}
        color_bonus = 0.5 * len(color_kw & item_colors)

        return content_score, content_score + color_bonus

    # Step 4: drop listings that don't meet the relevance threshold.
    # Threshold is applied to content_score only (not the color bonus).
    # Strict mode: require strictly more than half the content keywords to match.
    # Loose mode (_loose=True): score title/tags only; require content_score >= 1.
    if _loose:
        scored = [(*score(l, full_text=False), l) for l in listings]
        scored = [(cs, ts, l) for cs, ts, l in scored if cs >= 1]
    else:
        scored = [(*score(l, full_text=True), l) for l in listings]
        threshold = (len(content_kw) if content_kw else len(all_kw)) * 0.5
        scored = [(cs, ts, l) for cs, ts, l in scored if cs > threshold]

    # Step 5: sort by total score (content + color bonus) descending
    scored.sort(key=lambda x: x[1], reverse=True)
    return [l for _, _, l in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.
    """
    try:
        client = _get_groq_client()

        item_desc = (
            f"'{new_item['title']}' — a {new_item['category']} item. "
            f"Colors: {', '.join(new_item['colors'])}. "
            f"Style tags: {', '.join(new_item['style_tags'])}. "
            f"Condition: {new_item['condition']}. "
            f"Description: {new_item['description']}"
        )

        wardrobe_items = wardrobe.get("items", [])

        if not wardrobe_items:
            prompt = (
                f"A user just found this secondhand item: {item_desc}\n\n"
                "They don't have a wardrobe saved yet. Give them general styling advice — "
                "what kinds of pieces pair well with this item, what aesthetic it suits, "
                "and 1–2 specific outfit ideas using common wardrobe staples. "
                "Be specific and conversational, like you're texting a friend who loves fashion. "
                "Keep it to 3–5 sentences."
            )
        else:
            wardrobe_text = "\n".join(
                f"- {item['name']} ({item['category']}, colors: {', '.join(item['colors'])}, "
                f"tags: {', '.join(item['style_tags'])})"
                + (f" — {item['notes']}" if item.get("notes") else "")
                for item in wardrobe_items
            )
            prompt = (
                f"A user is considering buying this secondhand item: {item_desc}\n\n"
                f"Here is their current wardrobe:\n{wardrobe_text}\n\n"
                "Suggest 1–2 complete outfit combinations that incorporate the new item "
                "with specific pieces from their wardrobe. Reference pieces by name. "
                "Be specific about the vibe or occasion each outfit suits. "
                "Write like you're texting a stylish friend — casual but specific. "
                "Keep it to 4–6 sentences total."
            )

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300,
        )

        result = response.choices[0].message.content.strip()
        return result if result else _suggest_outfit_fallback(new_item)

    except Exception:
        return _suggest_outfit_fallback(new_item)


def _suggest_outfit_fallback(new_item: dict) -> str:
    tags = ", ".join(new_item.get("style_tags", []))
    category = new_item.get("category", "piece")
    return (
        f"Could not generate outfit suggestions at this time. "
        f"This {category} has a {tags} aesthetic — "
        f"it would pair well with classic basics like straight-leg jeans, "
        f"simple sneakers, or a minimal tote."
    )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)
    """
    # Guard against empty outfit
    if not outfit or not outfit.strip():
        return (
            "Cannot generate a fit card without an outfit suggestion — "
            "please try again with a complete outfit."
        )

    try:
        client = _get_groq_client()

        title = new_item.get("title", "this piece")
        price = new_item.get("price", "?")
        platform = new_item.get("platform", "a thrift app")

        prompt = (
            f"Write a 2–4 sentence Instagram/TikTok caption for this thrifted outfit.\n\n"
            f"Item found: {title}, ${price} on {platform}\n"
            f"Outfit: {outfit}\n\n"
            "Rules:\n"
            "- Sound like a real person, not a brand post (casual, conversational)\n"
            "- Mention the item name, price, and platform exactly once each\n"
            "- Capture the specific vibe of the outfit in concrete terms\n"
            "- 2–4 sentences max\n"
            "- No hashtags\n"
            "- Do NOT start with 'I' or 'This'\n"
            "Write just the caption, nothing else."
        )

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=150,
        )

        result = response.choices[0].message.content.strip()
        return result if result else _fit_card_fallback(new_item)

    except Exception:
        return _fit_card_fallback(new_item)


def _fit_card_fallback(new_item: dict) -> str:
    title = new_item.get("title", "this piece")
    price = new_item.get("price", "?")
    platform = new_item.get("platform", "a thrift app")
    return (
        f"Fit card generation failed. "
        f"Here's the item: {title} for ${price} on {platform}."
    )
