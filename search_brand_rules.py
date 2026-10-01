"""Validate LLM brand selections against catalogue labels, without brand-specific rules."""
import re

RULE_VERSION = "catalogue-labels-v1"
EXACT_WORDS = {"only", "exclusively", "sirf", "सिर्फ", "केवल"}


class GroundingError(ValueError):
    """A fixed server-owned diagnostic, safe for logs and repair feedback."""


def exact_requested(query):
    # Conservative: exclusivity or exclusion language prevents expansion.
    words = EXACT_WORDS | {"without", "except", "excluding", "exclude", "not", "nahi", "नहीं"}
    return any(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", query.casefold()) for word in words)


def catalogue_variant(requested, selected, categories, taxonomy):
    """A more specific catalogue label must preserve the complete requested name."""
    return (requested != selected and selected in taxonomy["brands"]
            and bool(re.search(r"(?<!\w)" + re.escape(requested.casefold()) + r"(?!\w)", selected.casefold()))
            and bool(set(categories) & set(taxonomy.get("brandCategories", {}).get(selected, []))))


def resolve_brands(brands, selected, categories, taxonomy, query, mode="family"):
    if mode not in {"family", "exact"}:
        raise ValueError("brandMatch must be family or exact")
    applied = list(selected or brands)
    expansions = []
    for brand in brands:
        variants = [b for b in applied if catalogue_variant(brand, b, categories, taxonomy)]
        if variants and (mode == "exact" or exact_requested(query)):
            raise GroundingError("AI changed an exact brand request")
        if brand not in applied and not variants:
            raise GroundingError("AI omitted an explicit brand")
        if variants:
            expansions.append({"requestedBrand": brand, "includedBrands": variants,
                               "reason": "llm_catalogue_brand_mapping",
                               "message": f"Interpreted {brand} as {' / '.join(variants)} for this product search."})
    if brands and any(b not in brands and not any(catalogue_variant(r, b, categories, taxonomy) for r in brands) for b in applied):
        raise GroundingError("AI substituted an unrelated brand")
    return applied, {"mode": "catalogue_mapping" if expansions else "exact", "requestedBrands": list(brands),
                     "appliedBrands": applied, "expansions": expansions, "ruleVersion": RULE_VERSION}
