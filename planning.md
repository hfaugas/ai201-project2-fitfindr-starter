# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the mock listings dataset for secondhand clothing items that match the user's description, optionally filtered by size and price. Returns a ranked list of matching listings sorted by keyword relevance, best match first.

**Input parameters:**
- `description` (str): Keywords describing the item the user wants (e.g., "vintage graphic tee", "track jacket"). Used for keyword overlap scoring against each listing's title, description, and style_tags.
- `size` (str): Size string to filter by, e.g. "M", "S/M", "W28". Matching is case-insensitive. Pass None to skip size filtering.
- `max_price` (float): Maximum price in dollars (inclusive). Pass None to skip price filtering.

**What it returns:**
A list of matching listing dicts, each containing: id (str), title (str), description (str), category (str), style_tags (list[str]), size (str), condition (str), price (float), colors (list[str]), brand (str or None), platform (str). Sorted by relevance score (highest first). Returns an empty list [] if nothing matches — never raises an exception.

**What happens if it fails or returns nothing:**
If the list is empty, the agent sets session["error"] to: "No listings found for '[description]'[size/price filter details]. Try broader keywords, a different size, or a higher price limit." The agent returns the session immediately without calling suggest_outfit or create_fit_card.

---

### Tool 2: suggest_outfit

**What it does:**
Calls the LLM (Groq llama-3.3-70b-versatile) to suggest 1–2 complete outfit combinations using the thrifted item and the user's existing wardrobe. If the wardrobe is empty, it provides general styling advice instead of crash-failing.

**Input parameters:**
- `new_item` (dict): The listing dict for the item the user is considering (from search_listings result). Contains title, description, style_tags, colors, etc.
- `wardrobe` (dict): A wardrobe dict with an 'items' key containing a list of wardrobe item dicts (each has name, category, colors, style_tags, notes). May have an empty items list.

**What it returns:**
A non-empty string with outfit suggestions. If the wardrobe has items, the response references specific pieces by name (e.g., "Pair this with your baggy straight-leg jeans and chunky white sneakers..."). If the wardrobe is empty, the response provides general styling advice for the item's aesthetic. Never returns an empty string or raises an exception.

**What happens if it fails or returns nothing:**
If the LLM call raises an exception or returns an empty string, the function catches the exception and returns: "Could not generate outfit suggestions at this time. The item is a [category] with [style_tags] — it would pair well with classic basics." This lets the agent continue to create_fit_card with partial data rather than crashing.

---

### Tool 3: create_fit_card

**What it does:**
Calls the LLM to generate a short, casual, shareable outfit caption (2–4 sentences) in the style of an Instagram or TikTok OOTD post. Uses a higher LLM temperature (0.9) to ensure varied output each run.

**Input parameters:**
- `outfit` (str): The outfit suggestion string returned by suggest_outfit(). If this is empty or whitespace-only, the function returns an error message without calling the LLM.
- `new_item` (dict): The listing dict for the thrifted item. Used to pull title, price, and platform into the caption naturally.

**What it returns:**
A 2–4 sentence string that sounds like a real OOTD caption: casual, specific about the vibe, mentions the item name/price/platform once each. Produces different output each run for the same inputs due to high temperature. If outfit is empty, returns: "Cannot generate a fit card without an outfit suggestion — please try again with a complete outfit."

**What happens if it fails or returns nothing:**
If outfit is empty/whitespace: return the error string above without calling the LLM. If the LLM call raises an exception: catch it and return "Fit card generation failed. Here's the item: [title] for $[price] on [platform]." so the user at least knows what was found.

---

### Additional Tools (if any)

None for required features.

---

## Planning Loop

**How does your agent decide which tool to call next?**

The planning loop in run_agent() executes the following conditional logic:

1. Initialize session with _new_session(query, wardrobe).
2. Parse the query using the LLM to extract description (str), size (str or None), and max_price (float or None). Store in session["parsed"].
3. Call search_listings(description, size, max_price). Store the result in session["search_results"].
   - **Branch A (no results):** If session["search_results"] == []: set session["error"] to a helpful message explaining what filters were active and what to try instead. Return session immediately. Do NOT proceed to suggest_outfit.
   - **Branch B (results found):** Continue to step 4.
4. Set session["selected_item"] = session["search_results"][0] (top-ranked match).
5. Call suggest_outfit(session["selected_item"], session["wardrobe"]). Store result in session["outfit_suggestion"].
6. Call create_fit_card(session["outfit_suggestion"], session["selected_item"]). Store result in session["fit_card"].
7. Return session.

The agent never calls suggest_outfit or create_fit_card unless search_listings returned at least one result. The only early-exit condition is an empty search result. All other errors within suggest_outfit and create_fit_card are handled inside those functions (they return error strings rather than raising exceptions), so the loop continues regardless.

---

## State Management

**How does information from one tool get passed to the next?**

A single session dict (initialized by _new_session()) is the shared state object for the entire interaction. It is mutated in place at each step:

- After parsing: session["parsed"] = {"description": ..., "size": ..., "max_price": ...}
- After search: session["search_results"] = [...list of dicts...]
- After selecting top result: session["selected_item"] = session["search_results"][0]
- After outfit: session["outfit_suggestion"] = "..."
- After fit card: session["fit_card"] = "..."
- On early exit: session["error"] = "..." (and other output fields remain None)

suggest_outfit receives session["selected_item"] directly as its new_item argument — no re-entry from the user. create_fit_card receives session["outfit_suggestion"] as its outfit argument. Each downstream tool call uses the value stored by the previous step. The session is returned from run_agent() so app.py can access all fields.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Returns [] (no exception). Agent sets session["error"] = "No listings found for '[keywords]'. Try removing the size filter or raising your price limit." Returns session early without calling later tools. |
| suggest_outfit | Wardrobe is empty (wardrobe["items"] == []) | Calls LLM with a general styling prompt instead of a wardrobe-specific one. Returns non-empty styling advice string. Agent continues normally to create_fit_card. |
| create_fit_card | Outfit input is empty or whitespace | Returns the string "Cannot generate a fit card without an outfit suggestion — please try again with a complete outfit." Agent surfaces this string to the user in the fit card panel. |

---

## Architecture

```
User query + wardrobe_choice
        │
        ▼
    app.py: handle_query()
        │ selects wardrobe (example or empty)
        │ calls run_agent(query, wardrobe)
        ▼
    agent.py: run_agent()
        │
        ├─ Step 1: _new_session(query, wardrobe)
        │          session = {query, parsed, search_results,
        │                     selected_item, wardrobe,
        │                     outfit_suggestion, fit_card, error}
        │
        ├─ Step 2: LLM parse → session["parsed"]
        │          {description, size, max_price}
        │
        ├─ Step 3: search_listings(description, size, max_price)
        │          session["search_results"] = [...]
        │                │
        │                ├─── results == [] ──► session["error"] = "No listings found..."
        │                │                     return session  ◄─── EARLY EXIT
        │                │
        │                └─── results found ──► continue
        │
        ├─ Step 4: session["selected_item"] = results[0]
        │
        ├─ Step 5: suggest_outfit(selected_item, wardrobe)
        │          session["outfit_suggestion"] = "..."
        │                │
        │                ├─── wardrobe empty ──► LLM gives general styling advice
        │                └─── wardrobe has items ──► LLM suggests specific combos
        │
        ├─ Step 6: create_fit_card(outfit_suggestion, selected_item)
        │          session["fit_card"] = "..."
        │                │
        │                └─── outfit empty ──► returns error string (no crash)
        │
        └─ Step 7: return session
                        │
                        ▼
    app.py: maps session fields to 3 Gradio output panels
        ├─ Panel 1 (listing):  format selected_item  OR  session["error"]
        ├─ Panel 2 (outfit):   session["outfit_suggestion"]
        └─ Panel 3 (fit card): session["fit_card"]
```

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

- **search_listings**: I used Claude and gave it the Tool 1 spec block (inputs, return fields, failure mode) plus the load_listings() docstring. I asked it to implement keyword scoring by tokenizing the description and checking overlap against title, description, and style_tags fields. I verified the output handles None size/price, returns [], and sorts by score before using it.

- **suggest_outfit**: I gave Claude the Tool 2 spec (inputs, empty wardrobe case, LLM model name) and asked it to produce two branches: one prompt for empty wardrobe (general styling) and one for non-empty (specific pieces). I checked that the generated code uses the correct Groq model and catches API exceptions.

- **create_fit_card**: I gave Claude the Tool 3 spec (empty outfit guard, caption style guidelines, temperature=0.9) and verified the generated code returns an error string rather than crashing when outfit is empty, and that temperature is set above 0.7.

**Milestone 4 — Planning loop and state management:**

- I gave Claude the Architecture diagram above plus the Planning Loop and State Management sections. I asked it to implement run_agent() following the numbered steps exactly. Before running it, I checked: (1) it branches on empty search_results, (2) it stores values in the session dict at each step, (3) it does not call suggest_outfit when results are empty.

---

## A Complete Interaction (Step by Step)

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**
The agent calls run_agent(query="I'm looking for a vintage graphic tee under $30...", wardrobe=get_example_wardrobe()). First, it parses the query via LLM to extract: description="vintage graphic tee", size=None (no size mentioned), max_price=30.0. Stores in session["parsed"].

**Step 2:**
search_listings("vintage graphic tee", size=None, max_price=30.0) is called. It loads all listings, filters to price ≤ $30, then scores each by keyword overlap with "vintage graphic tee". Items whose title, description, or style_tags contain "vintage", "graphic", or "tee" get scored. The function returns a ranked list — for example, the Y2K Baby Tee at $18 and the Faded Band Tee (if present) score highest. session["search_results"] = [<Y2K Baby Tee>, ...]. session["selected_item"] = session["search_results"][0] (the Y2K Baby Tee at $18 on depop).

**Step 3:**
suggest_outfit(new_item=<Y2K Baby Tee dict>, wardrobe=<example wardrobe>) is called. The wardrobe has 10 items, so the LLM receives a prompt listing them all and is asked to suggest specific outfit combos with the baby tee. It returns something like: "Pair this Y2K butterfly tee with your baggy straight-leg dark wash jeans and chunky white sneakers for a classic early-2000s look. You could also layer your vintage black denim jacket over it and swap to black combat boots for an edgier vibe." Stored in session["outfit_suggestion"].

**Step 4:**
create_fit_card(outfit=<suggestion string>, new_item=<Y2K Baby Tee dict>) is called. The LLM generates a caption: "thrifted this Y2K butterfly baby tee off depop for $18 and it's honestly been living in my rotation 🦋 paired it with my baggy dark jeans and chunky sneakers and the fit just came together perfectly, very 2003 in the best way". Stored in session["fit_card"].

**Final output to user:**
- **Panel 1 (listing):** "Y2K Baby Tee — Butterfly Print | $18.00 | depop | Size: S/M | Condition: excellent | Style: y2k, vintage, graphic tee, cottagecore"
- **Panel 2 (outfit):** The full outfit suggestion string from Step 3.
- **Panel 3 (fit card):** The caption string from Step 4.
