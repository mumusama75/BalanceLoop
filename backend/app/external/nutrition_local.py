"""Local, versioned nutrition table — stands in for the Nutrition Data Provider.

Deterministic helpers used by the Nutrition Coach (and by the mock LLM):
* alias lookup / fuzzy lookup of foods,
* portion parsing ("2 eggs", "a bowl of rice", "150g chicken"),
* nutrient estimation with an uncertainty range,
* allergen matching against the user's authorised allergy list.
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .data_source import ExternalDataSource

DATA_FILE = Path(__file__).parent / "data" / "nutrition_v1.json"

ALLERGY_SYNONYMS: Dict[str, List[str]] = {
    "peanut": ["peanut", "peanuts", "groundnut", "satay"],
    "tree_nut": ["tree nut", "tree nuts", "nuts", "nut", "almond", "walnut", "cashew", "hazelnut", "pecan", "pistachio", "nut allergy"],
    "milk": ["milk", "dairy", "lactose", "cheese", "yogurt", "yoghurt", "butter", "cream"],
    "egg": ["egg", "eggs"],
    "wheat": ["wheat"],
    "gluten": ["gluten", "celiac", "coeliac"],
    "soy": ["soy", "soya", "soybean", "tofu"],
    "fish": ["fish", "salmon", "tuna", "cod"],
    "shellfish": ["shellfish", "shrimp", "prawn", "prawns", "crab", "lobster", "seafood"],
    "sesame": ["sesame", "tahini"],
}

WORD_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "half": 0.5, "quarter": 0.25, "couple": 2, "few": 3, "some": 1}
PORTION_UNITS = ["bowl", "small bowl", "cup", "glass", "slice", "slices", "piece", "pieces", "tbsp", "tsp",
                 "handful", "plate", "can", "bottle", "bar", "egg", "eggs", "fillet", "burger", "sandwich",
                 "pack", "roll", "square", "cob", "half", "whole", "pot", "medium", "large", "small", "pint", "steak", "chop"]


def normalise_allergies(user_allergies: Iterable[str]) -> Set[str]:
    """Map free-text allergies ("Peanuts", "dairy") onto the controlled allergen vocabulary.

    Whole-word matching: "peanuts" maps to peanut only (not to tree_nut via the substring "nut").
    """
    keys: Set[str] = set()
    for raw in user_allergies or []:
        low = raw.strip().lower()
        if not low:
            continue
        for key, syns in ALLERGY_SYNONYMS.items():
            if low == key or any(re.search(rf"\b{re.escape(s)}(es|s)?\b", low) for s in syns):
                keys.add(key)
    return keys


class LocalNutritionSource(ExternalDataSource):
    def __init__(self, path: Path = DATA_FILE):
        data = json.loads(Path(path).read_text())
        self.version: str = data["version"]
        self.source_name: str = data["source"]
        self.foods: List[Dict[str, Any]] = data["foods"]
        self._by_id = {f["id"]: f for f in self.foods}
        self._alias_index: Dict[str, Dict[str, Any]] = {}
        for f in self.foods:
            for alias in [f["name"], *f["aliases"]]:
                self._alias_index[alias.lower()] = f
        # longest aliases first so "peanut butter" wins over "peanut"
        self._aliases_sorted = sorted(self._alias_index.keys(), key=len, reverse=True)

    # ---- ExternalDataSource
    def fetch_nutrition_data(self, query: str) -> Optional[Dict[str, Any]]:
        return self.lookup(query)

    # ---- lookup
    @staticmethod
    def _clean_query(name: str) -> str:
        q = name.strip().lower()
        q = re.sub(r"\([^)]*\)", " ", q)                                   # "(without peanuts)"
        q = re.sub(r"\b(without|no|free of|excluding|minus|hold the)\b.*$", " ", q)  # "… without nuts"
        q = re.sub(r"\b[\w-]+-free\b", " ", q)                              # "nut-free"
        q = re.sub(r"\b(grilled|boiled|steamed|fried|baked|roasted|cooked|fresh|plain|raw|stir-fried|homemade)\b", " ", q)
        return re.sub(r"\s+", " ", q).strip()

    def lookup(self, name: str) -> Optional[Dict[str, Any]]:
        if not name:
            return None
        q = self._clean_query(name)
        if not q:
            return None
        if q in self._alias_index:
            return self._alias_index[q]
        if q.endswith("s") and q[:-1] in self._alias_index:
            return self._alias_index[q[:-1]]
        for alias in self._aliases_sorted:
            if re.search(rf"\b{re.escape(alias)}\b", q):
                return self._alias_index[alias]
        close = difflib.get_close_matches(q, self._aliases_sorted, n=1, cutoff=0.85)
        return self._alias_index[close[0]] if close else None

    def find_in_text(self, text: str) -> List[Tuple[Dict[str, Any], str, Tuple[int, int]]]:
        """Find every known food mentioned in *text* (used by the mock LLM)."""
        low = text.lower()
        found: List[Tuple[Dict[str, Any], str, Tuple[int, int]]] = []
        taken: List[Tuple[int, int]] = []
        for alias in self._aliases_sorted:
            for m in re.finditer(rf"\b{re.escape(alias)}\b", low):
                span = m.span()
                if any(not (span[1] <= a or span[0] >= b) for a, b in taken):
                    continue
                taken.append(span)
                found.append((self._alias_index[alias], alias, span))
        found.sort(key=lambda t: t[2][0])
        # de-duplicate the same food mentioned twice
        seen, out = set(), []
        for f, alias, span in found:
            if f["id"] in seen:
                continue
            seen.add(f["id"])
            out.append((f, alias, span))
        return out

    # ---- portions
    def parse_portion(self, segment: str, food: Dict[str, Any]) -> Tuple[Optional[float], str, Optional[str]]:
        """Return (grams, evidence, description). evidence ∈ {stated, inferred, none}."""
        seg = segment.lower()
        g = re.search(r"(\d+(?:\.\d+)?)\s*(g|gram|grams|ml)\b", seg)
        if g:
            return float(g.group(1)), "stated", g.group(0)
        qty = None
        m = re.search(r"(\d+(?:\.\d+)?|" + "|".join(WORD_NUMBERS) + r")\s+(?:of\s+)?(" + "|".join(PORTION_UNITS) + r")\b", seg)
        if m:
            raw_q, unit = m.group(1), m.group(2)
            qty = float(raw_q) if raw_q[0].isdigit() else WORD_NUMBERS[raw_q]
            unit_s = unit.rstrip("s") if unit not in ("eggs",) else "egg"
            words = food.get("portion_words", {})
            per_unit = words.get(unit) or words.get(unit_s)
            if per_unit is None and unit_s in ("piece", "egg", "medium", "whole"):
                per_unit = food["typical_portion_g"]
            if per_unit is None and unit_s == "half":
                return food["typical_portion_g"] * 0.5, "inferred", m.group(0)
            if per_unit is not None:
                return qty * per_unit, "stated", m.group(0)
        n = re.search(r"\b(\d+(?:\.\d+)?)\b", seg)
        if n:
            return float(n.group(1)) * food["typical_portion_g"], "inferred", n.group(0)
        return None, "none", None

    # ---- estimation
    def estimate(self, food: Dict[str, Any], grams: float) -> Dict[str, float]:
        k = grams / 100.0
        p = food["per_100g"]
        return {"kcal": round(p["kcal"] * k, 1), "protein_g": round(p["protein_g"] * k, 1),
                "carbs_g": round(p["carbs_g"] * k, 1), "fat_g": round(p["fat_g"] * k, 1)}

    @staticmethod
    def range_for(grams: float, evidence: str) -> Tuple[float, float]:
        spread = {"stated": 0.15, "inferred": 0.35, "none": 0.5}[evidence]
        return round(grams * (1 - spread), 1), round(grams * (1 + spread), 1)

    # ---- allergens
    def allergens_of(self, food: Dict[str, Any]) -> List[str]:
        return list(food.get("allergens", []))

    def allergen_conflicts(self, foods: Iterable[Dict[str, Any]], user_allergies: Iterable[str]) -> List[Dict[str, str]]:
        keys = normalise_allergies(user_allergies)
        hits = []
        for f in foods:
            for a in f.get("allergens", []):
                if a in keys:
                    hits.append({"food": f["name"], "allergen": a})
        return hits


_default: Optional[LocalNutritionSource] = None


def get_nutrition_source() -> LocalNutritionSource:
    global _default
    if _default is None:
        _default = LocalNutritionSource()
    return _default
