# FitFindr

A multi-tool AI agent that helps users find secondhand clothing and figure out how to wear it. Built with Groq (llama-3.3-70b-versatile) and Gradio.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate      # Mac/Linux
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
GROQ_API_KEY=your_key_here
```

Run the app:

```bash
python app.py
```

Then open the URL shown in your terminal (usually `http://localhost:7860`).

Run tests:

```bash
pytest tests/
```

---

## Tool Inventory

### `search_listings(description, size, max_price)`

**Purpose:** Searches the mock listings dataset for secondhand items that match a natural language description, with optional size and price filters. No LLM — pure keyword scoring over the dataset.

| Parameter | Type | Description |
|---|---|---|
| `description` | `str` | Keywords describing the item (e.g. `"vintage graphic tee"`) |
| `size` | `str \| None` | Size filter, case-insensitive substring match (e.g. `"M"`, `"W28"`). `None` skips filter. |
| `max_price` | `float \| None` | Price ceiling, inclusive. `None` skips filter. |

**Returns:** `list[dict]` — matching listing dicts sorted by keyword relevance (best match first). Each dict contains: `id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition`, `price` (float), `colors` (list), `brand`, `platform`. Returns `[]` if nothing matches — never raises.

---

### `suggest_outfit(new_item, wardrobe)`

**Purpose:** Calls the LLM to suggest 1–2 complete outfit combinations using a thrifted item and the user's wardrobe. Handles empty wardrobes by offering general styling advice instead of crashing.

| Parameter | Type | Description |
|---|---|---|
| `new_item` | `dict` | Listing dict for the item being considered |
| `wardrobe` | `dict` | Wardrobe dict with `items` key (list of wardrobe item dicts). May be empty. |

**Returns:** `str` — non-empty outfit suggestion. If wardrobe has items, references specific pieces by name. If empty, provides general styling advice for the item's aesthetic. Never returns an empty string or raises.

---

### `create_fit_card(outfit, new_item)`

**Purpose:** Calls the LLM at high temperature (0.9) to generate a casual, shareable 2–4 sentence caption in the style of an OOTD Instagram post.

| Parameter | Type | Description |
|---|---|---|
| `outfit` | `str` | Outfit suggestion from `suggest_outfit()`. Empty string triggers an error return (no LLM call). |
| `new_item` | `dict` | Listing dict — used for item name, price, and platform in the caption |

**Returns:** `str` — casual caption mentioning item name, price, and platform once each. Different output on each call for the same input (high temperature). Returns a descriptive error string if `outfit` is empty — never raises.

---

## How the Planning Loop Works

`run_agent()` in `agent.py` executes this conditional sequence:

1. **Parse** — the LLM extracts `description`, `size`, and `max_price` from the user's natural language query. Falls back to regex if the LLM call fails.

2. **Search** — calls `search_listings(description, size, max_price)`.
   - **If results are empty:** sets `session["error"]` to a message explaining which filters were active and what to try instead, then **returns immediately** without calling the remaining tools.
   - **If results found:** stores the top result in `session["selected_item"]` and continues.

3. **Outfit** — calls `suggest_outfit(selected_item, wardrobe)`. Always produces a string (wardrobe-specific or general), so the loop continues.

4. **Fit card** — calls `create_fit_card(outfit_suggestion, selected_item)`. Guards against empty outfit internally.

5. **Return** — returns the full session dict. The UI maps session fields to three output panels.

The key behavioral branch is step 2: `suggest_outfit` and `create_fit_card` are **never called** when `search_listings` returns nothing. This is what makes the loop conditional rather than a fixed sequence.

---

## State Management

A single `session` dict (created by `_new_session()`) is the shared state object for the entire interaction:

```
session["parsed"]            ← set after query parsing
session["search_results"]    ← set after search_listings()
session["selected_item"]     ← set to search_results[0] if results found
session["outfit_suggestion"] ← set after suggest_outfit()
session["fit_card"]          ← set after create_fit_card()
session["error"]             ← set on early exit (all other fields stay None)
```

Each tool receives its inputs directly from the session — `suggest_outfit` gets `session["selected_item"]`, `create_fit_card` gets `session["outfit_suggestion"]`. No re-entry from the user between steps. The session is returned from `run_agent()` and `app.py` maps its fields to the three Gradio output panels.

---

## Interaction Walkthrough

**User query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers."

**Step 1 — Tool called: `search_listings`**
- Tool: `search_listings`
- Input: `description="vintage graphic tee"`, `size=None`, `max_price=30.0`
- Why this tool: The agent parses the query and sees a description + price limit. This is always the first tool — it finds the item before anything else can happen.
- Output: List of matching items sorted by relevance. Top result: Y2K Baby Tee — Butterfly Print, $18, depop. This gets stored as `session["selected_item"]`.

**Step 2 — Tool called: `suggest_outfit`**
- Tool: `suggest_outfit`
- Input: `new_item=<Y2K Baby Tee dict>`, `wardrobe=<example wardrobe with 10 items>`
- Why this tool: A listing was found (non-empty results), so the agent proceeds to styling. The item dict flows directly from `session["selected_item"]` — no user re-entry.
- Output: "Pair this Y2K butterfly tee with your baggy straight-leg dark wash jeans and chunky white sneakers for a classic early-2000s look. You could also layer your vintage black denim jacket over it and swap to black combat boots for an edgier vibe." Stored as `session["outfit_suggestion"]`.

**Step 3 — Tool called: `create_fit_card`**
- Tool: `create_fit_card`
- Input: `outfit=<suggestion from step 2>`, `new_item=<Y2K Baby Tee dict>`
- Why this tool: There's a non-empty outfit suggestion, so the agent generates a shareable caption from it.
- Output: "thrifted this Y2K butterfly baby tee off depop for $18 and it's honestly been living in my rotation 🦋 paired it with my baggy dark jeans and chunky white sneakers and the whole thing just came together, very 2003 in the best way"

**Final output to user:**
- Panel 1: Formatted listing card (title, price, platform, size, condition, style tags, description)
- Panel 2: Outfit suggestion referencing specific wardrobe pieces by name
- Panel 3: The fit card caption ready to copy-paste

---

## Error Handling and Fail Points

| Tool | Failure mode | Agent response |
|---|---|---|
| `search_listings` | No listings match query/filters | Returns `[]`. Agent sets `session["error"]` = "No listings found for '[keywords]'[active filters]. Try broader keywords, remove the size filter, or raise your price limit." Returns session without calling later tools. |
| `suggest_outfit` | Wardrobe is empty (`wardrobe["items"] == []`) | Calls LLM with a general styling prompt instead of a wardrobe-specific one. Returns useful styling advice string. Agent continues to `create_fit_card` normally. |
| `suggest_outfit` | LLM API exception | Catches exception, returns a fallback string: "Could not generate outfit suggestions at this time. This [category] has a [tags] aesthetic — it would pair well with classic basics like straight-leg jeans, simple sneakers, or a minimal tote." |
| `create_fit_card` | `outfit` is empty or whitespace | Returns "Cannot generate a fit card without an outfit suggestion — please try again with a complete outfit." without calling the LLM at all. |
| `create_fit_card` | LLM API exception | Catches exception, returns "Fit card generation failed. Here's the item: [title] for $[price] on [platform]." |

**Concrete example from testing:**

Running `search_listings("designer ballgown", size="XXS", max_price=5)` returns `[]`. The agent sets:

```
session["error"] = "No listings found for 'designer ballgown' with filters: size 'XXS', max price $5. Try broader keywords, remove the size filter, or raise your price limit."
```

The UI displays this message in panel 1. Panels 2 and 3 are empty. The user sees exactly what filters were active and has specific actions to try.

---

## Spec Reflection

**One way planning.md helped during implementation:**

Writing the error handling table before coding forced a concrete decision about what each failure mode actually returns. For `suggest_outfit`, I initially thought "just return an empty string on failure" — but the spec required a specific, informative message. That forced the two-branch design: if `wardrobe["items"]` is empty, use a different prompt (general styling advice); if the LLM call throws, use the `_suggest_outfit_fallback()` helper. The spec made those two failure modes distinct rather than conflated.

**One divergence from the spec, and why:**

The spec describes query parsing as a single LLM call with no fallback. In implementation, I added `_parse_query_regex()` as a fallback because an LLM failure during parsing would silently produce empty strings for `description`, `size`, and `max_price`, which would cause `search_listings` to return no results with no useful error message — the user would see "no results" when the real problem was a failed API call. The regex fallback recovers from this silently and lets the agent continue usefully. This wasn't in the original design but was necessary for robustness at the first step of the pipeline.

---

## AI Usage

**Instance 1 — `search_listings` implementation:**

I gave Claude the Tool 1 spec from `planning.md` (inputs, return value, failure mode) and the `load_listings()` docstring, and asked it to implement keyword scoring using regex tokenization against title, description, and style_tags. The generated code used a single combined text string for scoring, which I kept. I modified the size filtering from an exact match to a bidirectional substring check (`size_lower in item["size"].lower() OR item["size"].lower() in size_lower`) after noticing that querying size "M" wouldn't match listings sized "S/M" with exact matching. Tested with `search_listings("tee", size="M")` and verified the fix before using the function.

**Instance 2 — `run_agent()` planning loop:**

I gave Claude the Architecture diagram (ASCII art from `planning.md`) plus the Planning Loop and State Management sections, and asked it to implement `run_agent()` following the numbered steps. The first generated version called all three tools in a fixed sequence without branching on empty search results — `suggest_outfit` was called with `None` as `new_item`. I identified the missing `if not session["search_results"]: return session` early-exit block, added it, and verified by running the no-results CLI test case (`python agent.py`) before using the implementation.
