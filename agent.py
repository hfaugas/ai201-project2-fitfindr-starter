"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from tools import search_listings, suggest_outfit, create_fit_card

load_dotenv()


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
        "fallback_search": False,    # str describing what was relaxed, or False
    }


# ── query parser ──────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Extract description, size, and max_price from a natural language query.
    Uses the LLM first; falls back to regex if the LLM call fails.

    Returns a dict with keys: description (str), size (str|None), max_price (float|None).
    """
    try:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("No API key")
        client = Groq(api_key=api_key)

        prompt = (
            "Extract structured search parameters from this clothing query.\n"
            f"Query: {query}\n\n"
            "Respond with ONLY these three lines (nothing else):\n"
            "description: <keywords for the item, e.g. 'vintage graphic tee'>\n"
            "size: <size string like M, S, XL, W28, or 'none' if not mentioned>\n"
            "max_price: <number like 30.0, or 'none' if not mentioned>\n"
        )

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=80,
        )
        text = response.choices[0].message.content.strip()

        parsed = {}
        for line in text.splitlines():
            if line.lower().startswith("description:"):
                parsed["description"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("size:"):
                val = line.split(":", 1)[1].strip()
                parsed["size"] = None if val.lower() == "none" else val
            elif line.lower().startswith("max_price:"):
                val = line.split(":", 1)[1].strip()
                try:
                    parsed["max_price"] = float(val) if val.lower() != "none" else None
                except ValueError:
                    parsed["max_price"] = None

        if "description" not in parsed or not parsed["description"]:
            raise ValueError("LLM parse missing description")

        parsed.setdefault("size", None)
        parsed.setdefault("max_price", None)
        return parsed

    except Exception:
        return _parse_query_regex(query)


def _parse_query_regex(query: str) -> dict:
    """Regex fallback for query parsing."""
    # Extract price: "under $30", "$30", "30 dollars", "max 30"
    price_match = re.search(
        r"(?:under|max|less than|below|up to)?\s*\$?(\d+(?:\.\d+)?)\s*(?:dollars?)?",
        query, re.IGNORECASE
    )
    max_price = float(price_match.group(1)) if price_match else None

    # Extract size: "size M", "size XL", or bare size tokens
    size_match = re.search(
        r"\bsize\s+([A-Z]{1,3}|\d+[A-Z]?\s*[A-Z]?\d*)\b"
        r"|\b(XS|S|M|L|XL|XXL|XXXL|W\d{2}(?:\s*L\d{2})?)\b",
        query, re.IGNORECASE
    )
    size = None
    if size_match:
        size = (size_match.group(1) or size_match.group(2) or "").strip() or None

    # Description: strip size/price tokens and clean up
    desc = query
    desc = re.sub(r"(?:under|max|less than|below|up to)?\s*\$\d+(?:\.\d+)?", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\bsize\s+\S+", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\b(XS|S|M|L|XL|XXL|XXXL|W\d{2}(?:\s*L\d{2})?)\b", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\b(I'm looking for|looking for|find me|I want|want a|I need)\b", "", desc, flags=re.IGNORECASE)
    desc = " ".join(desc.split()).strip(" .,?!")
    if not desc:
        desc = query

    return {"description": desc, "size": size, "max_price": max_price}


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.
    """
    # Step 1: initialize session
    session = _new_session(query, wardrobe)

    # Step 2: parse the query to extract description, size, max_price
    session["parsed"] = _parse_query(query)
    description = session["parsed"]["description"]
    size = session["parsed"].get("size")
    max_price = session["parsed"].get("max_price")

    # Step 3: search listings — strict pass first
    session["search_results"] = search_listings(description, size, max_price)
    session["fallback_search"] = False

    # Branch A: no results → retry with loosened constraints before giving up
    if not session["search_results"]:
        # Retry 1: drop price filter
        if max_price is not None:
            session["search_results"] = search_listings(description, size, None)
            if session["search_results"]:
                session["fallback_search"] = f"removed the ${max_price:.0f} price limit"

        # Retry 2: drop both price and size filters, use loose keyword matching
        if not session["search_results"]:
            session["search_results"] = search_listings(
                description, None, None, _loose=True
            )
            if session["search_results"]:
                removed = []
                if size:
                    removed.append(f"size '{size}'")
                if max_price is not None:
                    removed.append(f"${max_price:.0f} price limit")
                removed_str = " and ".join(removed) if removed else "all filters"
                session["fallback_search"] = f"removed {removed_str} and broadened keyword matching"

    # Branch A: still nothing after retries → early exit
    if not session["search_results"]:
        filters = []
        if size:
            filters.append(f"size '{size}'")
        if max_price is not None:
            filters.append(f"max price ${max_price:.0f}")
        filter_str = f" with filters: {', '.join(filters)}" if filters else ""
        session["error"] = (
            f"No listings found for '{description}'{filter_str}. "
            "Try broader keywords, remove the size filter, or raise your price limit."
        )
        return session

    # Branch B: results found → continue
    # Step 4: select top result
    session["selected_item"] = session["search_results"][0]

    # Step 5: suggest outfit
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"], session["wardrobe"]
    )

    # Step 6: create fit card
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )

    # Step 7: return session
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
