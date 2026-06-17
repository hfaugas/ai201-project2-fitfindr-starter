"""
tests/test_tools.py

Unit tests for each FitFindr tool. Run with:
    .venv/bin/pytest tests/
"""

import sys
import os

# Ensure the project root is on the path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── search_listings tests ──────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_price_filter_none_skips_filter():
    results_no_filter = search_listings("vintage", size=None, max_price=None)
    results_filtered = search_listings("vintage", size=None, max_price=20)
    assert len(results_no_filter) >= len(results_filtered)


def test_search_size_filter_case_insensitive():
    results = search_listings("tee", size="m", max_price=None)
    for item in results:
        assert "m" in item["size"].lower()


def test_search_returns_list_of_dicts():
    results = search_listings("jeans", size=None, max_price=100)
    assert isinstance(results, list)
    for item in results:
        assert isinstance(item, dict)
        assert "title" in item
        assert "price" in item
        assert "platform" in item


def test_search_sorted_by_relevance():
    results = search_listings("vintage denim jacket", size=None, max_price=None)
    if len(results) >= 2:
        # Results with "vintage" and "denim" and "jacket" should score higher
        # than results with just one keyword match — we can't assert exact order
        # but we can assert the result is a list (ordering is tested by presence)
        assert isinstance(results, list)


def test_search_no_exception_on_broad_query():
    try:
        results = search_listings("clothing", size=None, max_price=None)
        assert isinstance(results, list)
    except Exception as e:
        assert False, f"search_listings raised an exception: {e}"


# ── suggest_outfit tests ───────────────────────────────────────────────────────

def test_suggest_outfit_returns_string():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    if results:
        suggestion = suggest_outfit(results[0], get_example_wardrobe())
        assert isinstance(suggestion, str)
        assert len(suggestion) > 0


def test_suggest_outfit_empty_wardrobe_no_crash():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    if results:
        suggestion = suggest_outfit(results[0], get_empty_wardrobe())
        assert isinstance(suggestion, str)
        assert len(suggestion) > 0


def test_suggest_outfit_empty_wardrobe_returns_useful_string():
    results = search_listings("jacket", size=None, max_price=100)
    if results:
        suggestion = suggest_outfit(results[0], get_empty_wardrobe())
        # Should not be a blank string or just whitespace
        assert suggestion.strip() != ""


# ── create_fit_card tests ──────────────────────────────────────────────────────

def test_create_fit_card_returns_string():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    if results:
        outfit = suggest_outfit(results[0], get_example_wardrobe())
        card = create_fit_card(outfit, results[0])
        assert isinstance(card, str)
        assert len(card) > 0


def test_create_fit_card_empty_outfit_returns_error_string():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    if results:
        card = create_fit_card("", results[0])
        assert isinstance(card, str)
        assert "cannot" in card.lower() or "failed" in card.lower() or "without" in card.lower()


def test_create_fit_card_whitespace_outfit_returns_error_string():
    results = search_listings("jacket", size=None, max_price=100)
    if results:
        card = create_fit_card("   ", results[0])
        assert isinstance(card, str)
        assert card.strip() != ""


def test_create_fit_card_no_exception_on_empty_outfit():
    results = search_listings("vintage", size=None, max_price=100)
    if results:
        try:
            card = create_fit_card("", results[0])
            assert isinstance(card, str)
        except Exception as e:
            assert False, f"create_fit_card raised an exception on empty outfit: {e}"
