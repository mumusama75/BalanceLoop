"""Keyword patterns shared by the hard rules (deterministic, explainable)."""
import re
from typing import List, Tuple

CRITICAL_SYMPTOM_PATTERNS = [
    r"chest pain", r"chest tightness", r"\bfaint(ed|ing)?\b", r"passed out", r"black(ed)? out",
    r"can'?t breathe", r"cannot breathe", r"shortness of breath", r"severe dizziness", r"numbness",
    r"heart (racing|palpitations)", r"vomit(ed|ing)? blood", r"severe pain", r"unbearable pain",
]
SELF_HARM_ED_PATTERNS = [
    r"\bpurg(e|ing)\b", r"throw(ing)? up after (eating|meals)", r"vomit(ing)? after (eating|meals)",
    r"\bstarv(e|ing) (myself|to lose|until)", r"\bwant to starve\b", r"\bdeserve to (eat|starve)\b",
    r"stop eating (entirely|completely|altogether)", r"not eat(ing)? (at all|anything) for", r"hurt myself", r"kill myself",
    r"\blaxatives?\b", r"\bbinge\b.*\bpurge\b", r"only (drink|have) water (tomorrow|all day|for a week)",
]
PUNITIVE_REQUEST_PATTERNS = [
    r"\bcompensat(e|ing|ion)\b", r"\bpunish", r"make up for (what|eating|the)", r"burn (it|that|off|the)",
    r"ate too much.*(so|therefore).*(skip|only|just|fast)", r"\bskip (dinner|lunch|breakfast|meals?)\b",
    r"only (drink|have) water", r"\bfast(ing)? (tomorrow|all day|for)", r"\bcut (calories|food) (hard|drastically|in half)\b",
    r"\bdouble (the|my) (workout|exercise|cardio)\b", r"\bextra (cardio|workout) to (burn|offset)",
    r"\bstricter\b", r"\bcheat(ed)?\b.*\b(so|now)\b.*(skip|cut|fast)",
]
# Directive phrases that make a PLAN punitive (used on outputs); the request patterns above are for the user's own words.
PUNITIVE_OUTPUT_PATTERNS = [
    r"\bskip (dinner|lunch|breakfast|meals?)\b", r"only (drink|have) water", r"\bfast(ing)? (tomorrow|all day|for)",
    r"\b(compensate|make up) for (eating|food|the meal|a meal|overeating|what you ate|the extra|yesterday|last night|the party|the calories)",
    r"\bburn (it|that|them|the (meal|food|calories)) off\b", r"\bdouble (the|your) (workout|exercise|cardio)\b",
    r"\bcut (calories|food|portions) (hard|drastically|in half)\b", r"\bpunish", r"\bextra (cardio|workout) to (burn|offset)",
    r"\bno (food|eating) (until|after)\b", r"\bstricter (plan|diet)\b",
]
MEDICAL_CLAIM_PATTERNS = [
    r"\bwill cure\b", r"\bcures?\b", r"\bdiagnos(e|is|ed)\b", r"\btreat(s|ment)? (your|the) (condition|disease|diabetes|hypertension)",
    r"\bprescri(be|ption)\b", r"\byou have (diabetes|hypertension|an eating disorder|a thyroid)", r"\bstop taking (your )?medication",
    r"\breplace(s)? (your )?(medication|insulin|therapy)\b", r"\bmedically proven\b",
]


NEGATION_WORDS = re.compile(r"\b(not|never|no|n't|without|avoid|rather than|instead of|isn't|is not|does not|doesn't|cannot|can't|won't|will not)\b")


def _negated(low: str, start: int) -> bool:
    """True when the match is preceded, within the same sentence and ~40 chars, by a negation."""
    window = low[max(0, start - 40):start]
    window = re.split(r"[.;!?\n]", window)[-1]
    return bool(NEGATION_WORDS.search(window))


def match_any(text: str, patterns: List[str], negation_aware: bool = False) -> List[str]:
    low = (text or "").lower()
    hits = []
    for p in patterns:
        for m in re.finditer(p, low):
            if negation_aware and _negated(low, m.start()):
                continue
            hits.append(p)
            break
    return hits


def describe_hits(hits: List[str]) -> str:
    return ", ".join(h.replace("\\b", "").replace("\\", "") for h in hits)
