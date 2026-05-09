# Suggestions

> **Note:** Once a suggestion is implemented, remove it from this file.

---

## 1. Add metaphor/analogy AVOID rule to query generation (Call 2 STEP 1)

**File:** `src/prompt_templates.py` — `generate_queries_from_scratchpad()`, STEP 1 AVOID reasons list

**Change:** Add a third explicit AVOID reason:

> Terms that describe the invention's appearance or structure using a biological or architectural metaphor (e.g., brick, mortar, nacre, scaffold, honeycomb, interlocking, bio-inspired, bottom-up) — these are analogies for how the structure looks, not the underlying technical mechanism. They only match patents where an inventor happened to use the same metaphor and are not reliable search anchors.

**Why:** The current scratchpad prompt guards against editorial terms at the concept-rating stage, but the LLM frequently rates these as "Well-placed" because they appear in academic literature. Moving the guard to the harder AVOID rule in Call 2 — where instruction-following is more reliable — is more effective.

---

## 2. Add conditional property-outcome AVOID rule based on statutory category

**File:** `src/prompt_templates.py` — `generate_queries_from_scratchpad()`, STEP 1 AVOID reasons list

**Change:** Add a fourth AVOID reason that is conditional on the invention's statutory category (already available in the prompt as `{category}`):

> **For Composition of Matter, Machine, and Process inventions:** Avoid standalone property-outcome terms — words that describe the performance benefit or improvement the invention achieves (e.g., ductility, strength, conductivity, toughness, efficiency, yield, throughput). These describe what the invention does, not what it structurally is. Search for the structural/compositional/mechanistic elements instead.
>
> **Exception:** If the statutory category is a Measurement or Testing method, or if the invention is defined by a specific property threshold as a claim-limiting feature (e.g., a superconductor defined by critical temperature, a dielectric defined by dielectric constant), the property term is a valid anchor and should be USE.

**Why:** The blanket version of this rule overcorrects for measurement-method inventions and property-threshold inventions (superconductors, superalloys, pharmaceuticals). Tying it to the `statutory_category` field — which the scratchpad always outputs — allows the correct logic to apply without manual per-run tuning.
