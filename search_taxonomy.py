"""Catalogue-derived family context; no customer-query synonym tables."""
import re
from difflib import SequenceMatcher


def category_stem(label):
    words = re.findall(r"\w+", label.casefold())
    if words:
        last = words[-1]
        if last.endswith("ies") and len(last) > 4:
            words[-1] = last[:-3] + "y"
        elif last.endswith("s") and not last.endswith("ss") and len(last) > 3:
            words[-1] = last[:-1]
    return " ".join(words)


def category_families(categories):
    """Group shared noun suffixes, keeping the most specific equal grouping."""
    groups = {}
    for category in categories:
        words = category_stem(category).split()
        for size in range(1, min(3, len(words)) + 1):
            groups.setdefault(" ".join(words[-size:]), []).append(category)
    families = {name: sorted(values) for name, values in groups.items() if len(values) > 1}
    return {name: values for name, values in families.items() if not any(
        other.endswith(" " + name) and members == values
        for other, members in families.items())}


def category_key(label):
    return re.sub(r"[^\w]", "", label.casefold())


class CategoryCatalogue:
    """Resolve catalogue structure locally; semantic synonyms still go to AI."""
    def __init__(self, taxonomy):
        self.indexed = taxonomy["categories"]
        self.nodes = {n["id"]: n for n in taxonomy.get("categoryTree", [])}
        self.children = {}
        for node in self.nodes.values():
            self.children.setdefault(node["parentId"], []).append(node["id"])
        self.names = {category_key(n["name"]): n for n in self.nodes.values() if n.get("active", True)}
        self.labels = {category_key(c): c for c in self.indexed}

    def descendants(self, node_id):
        pending, visited, labels = [node_id], set(), set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            node = self.nodes.get(current)
            if not node:
                continue
            label = self.labels.get(category_key(node["name"]))
            if label:
                labels.add(label)
            pending.extend(self.children.get(current, []))
        return sorted(labels)

    def describe(self, requested):
        result = {"requestedCategory": requested, "canonicalCategory": None,
                  "matchType": "unknown", "matchedCategories": [], "suggestedCategories": [],
                  "requiredTerms": []}
        key = category_key(requested)
        node = self.names.get(key)
        exact = self.labels.get(key)
        if node:
            result["canonicalCategory"] = node["name"]
            scope = self.descendants(node["id"])
            if scope:
                result.update(matchType="family" if len(scope) > 1 or not exact else "exact", matchedCategories=scope)
                return result
        elif exact:
            result.update(canonicalCategory=exact, matchType="exact", matchedCategories=[exact])
            return result
        # Singular/plural label differences do not change the requested function.
        equivalent = [c for c in self.indexed if category_stem(c) == category_stem(requested)]
        if equivalent:
            scopes = set(equivalent)
            for label in equivalent:
                parent = self.names.get(category_key(label))
                if parent:
                    scopes.update(self.descendants(parent["id"]))
            result.update(canonicalCategory=equivalent[0], matchType="equivalent", matchedCategories=sorted(scopes))
            return result
        if node:
            visited = {node["id"]}
            parent = self.nodes.get(node["parentId"])
            distance = 1
            while parent and parent["id"] not in visited:
                visited.add(parent["id"])
                related = self.descendants(parent["id"])
                if related:
                    # A master/export spelling difference must not invent a
                    # missing subtype. Accept only one-letter, nonnumeric,
                    # unambiguous equivalents within the same parent scope.
                    close = []
                    for label in related:
                        candidate = category_key(label)
                        differences = [(a, b) for a, b in zip(key, candidate) if a != b]
                        if (len(key) >= 7 and len(key) == len(candidate) and len(differences) == 1
                                and not any(char.isdigit() for pair in differences for char in pair)):
                            close.append(label)
                    if len(close) == 1:
                        result.update(canonicalCategory=close[0], matchType="equivalent", matchedCategories=close)
                        return result
                    shared = set(" ".join(category_stem(c) for c in related).split())
                    terms = [w for w in category_stem(node["name"]).split() if w not in shared]
                    same_family = any(set(members) == set(related) for members in category_families(related).values())
                    same_single_function = (len(related) == 1 and category_stem(node["name"]).split()[-1:]
                                            == category_stem(related[0]).split()[-1:])
                    allow_alternatives = distance == 1 and (same_family or same_single_function)
                    result.update(matchType="attribute", matchedCategories=related,
                                  suggestedCategories=related if allow_alternatives else [],
                                  requiredTerms=terms or [category_stem(node["name"])], _allowAlternatives=allow_alternatives)
                    return result
                parent = self.nodes.get(parent["parentId"])
                distance += 1
            result["matchType"] = "unavailable"
            return result
        # Only unambiguous spelling corrections. Different product functions
        # require the semantic interpreter rather than a nearest-name guess.
        choices = {n["name"] for n in self.names.values()} | set(self.indexed)
        scores = sorted(((SequenceMatcher(None, key, category_key(c)).ratio(), c) for c in choices), reverse=True)
        if (len(key) >= 5 and scores and scores[0][0] >= .90
                and (len(scores) == 1 or scores[0][0] - scores[1][0] >= .08)):
            mapped = self.describe(scores[0][1])
            mapped["requestedCategory"] = requested
            mapped["correction"] = scores[0][1]
            return mapped
        return result

    def mentioned(self, query):
        result = []
        for node in self.names.values():
            if re.search(r"(?<!\w)" + re.escape(node["name"].casefold()) + r"(?!\w)", query.casefold()):
                result.append(self.describe(node["name"]))
        return result

    def parent_aliases(self):
        aliases = {}
        for node in self.names.values():
            scope = self.descendants(node["id"])
            if scope:
                aliases[node["name"].casefold()] = scope
                aliases[category_stem(node["name"])] = scope
        return aliases
