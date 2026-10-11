"""English words written in Arabic letters ("فين بسكت بال؟" = "where is basketball?").

Egyptian students often write English campus words in Arabic letters. The embedding
model does not recognise these, so before searching, the English word is added to the
question. Spelling varies a lot, so letters are normalised first (أ/إ/آ -> ا, ى -> ي,
ة -> ه, no diacritics) and an optional "ال" in front of a word is allowed.
"""
import re

# English term -> ways people write it in Arabic letters (already normalised, without "ال").
GLOSSARY = {
    "basketball": ["بسكت بال", "بسكت بول", "باسكت بال", "باسكت بول", "بسكتبول", "باسكتبول", "باسكت", "بسكت"],
    "football": ["فوتبول", "فوت بول", "فوتبال"],
    "field": ["فيلد"],
    "tennis": ["تنس", "تينس"],
    "court": ["كورت", "كورط"],
    "gym": ["جيم", "جم"],
    "supermarket": ["سوبر ماركت", "سوبرماركت", "ماركت"],
    "food court": ["فود كورت", "فودكورت"],
    "padel": ["بادل", "باديل"],
    "clinic": ["كلينك", "كلينيك"],
    "library": ["لايبراري", "لايبرري", "ليبراري"],
    "student affairs": ["ستيودنت افيرز", "ستودنت افيرز", "ستيودنت افيرس", "ستودنت افيرس"],
    "admission": ["ادميشن", "ادمشن", "ادميشنز"],
    "office": ["اوفيس", "افيس"],
    "AI lab": ["ايه اي لاب", "اي اي لاب", "ايه اي"],
    "lab": ["لاب", "لابز"],
    "finance": ["فاينانس", "فايننس", "فينانس"],
    "German office": ["جيرمان اوفيس", "جرمان اوفيس"],
    "German": ["جيرمان", "جرمان"],
    "academic coordinator": ["اكاديمك كوردينيتور", "اكاديميك كوردينيتور"],
    "coordinator": ["كوردينيتور", "كوردنيتور"],
    "research": ["ريسيرش", "ريسرش"],
    "grant": ["جرانت"],
    "thesis": ["ثيسيس", "تيزيس"],
    "supervisor": ["سوبرفايزر", "سوبر فايزر"],
    "deadline": ["ديدلاين"],
    "tuition fees": ["تيوشن فيز", "تويشن فيز"],
    "tuition": ["تيوشن", "تويشن"],
    "electronics": ["الكترونكس", "اليكترونكس"],
    "building": ["بيلدنج", "بلدنج"],
    "room": ["روم"],
    "floor": ["فلور"],
}

_DIACRITICS = re.compile(r"[ً-ْـ]")  # harakat and tatweel


def normalize_arabic(text: str) -> str:
    text = _DIACRITICS.sub("", text)
    text = re.sub("[أإآ]", "ا", text)
    return text.replace("ى", "ي").replace("ة", "ه")


def _pattern(variants: list[str]) -> re.Pattern:
    """Whole words only, with an optional "ال" in front."""
    alternatives = "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
    return re.compile(r"(?:^|(?<=[\s،؟?.!,]))(?:ال)?(?:" + alternatives + r")(?=$|[\s،؟?.!,])")


_TERM_PATTERNS = [(english, _pattern(variants)) for english, variants in GLOSSARY.items()]
# For replacing: longest spellings first across all terms, so "فود كورت" -> "food court"
# happens before "كورت" -> "court".
_REPLACEMENTS = sorted(((variant, english) for english, variants in GLOSSARY.items() for variant in variants),
                       key=lambda pair: len(pair[0]), reverse=True)


def english_terms(text: str) -> list[str]:
    """English terms written in Arabic letters in the text, e.g. ["basketball"]."""
    normalized = normalize_arabic(text)
    return [english for english, pattern in _TERM_PATTERNS if pattern.search(normalized)]


def with_english_terms(text: str) -> str:
    """The text plus the English terms it contains: "فين بسكت بال؟ (basketball)"."""
    terms = english_terms(text)
    return f"{text} ({', '.join(terms)})" if terms else text


def to_english_words(text: str) -> str:
    """The text with those words replaced by English: "فين basketball ؟"."""
    out = normalize_arabic(text)
    for variant, english in _REPLACEMENTS:
        out = _pattern([variant]).sub(english, out)
    return " ".join(out.split())


def search_variants(text: str) -> list[str]:
    """Ways to search for a question. With English words written in Arabic letters, both
    forms are searched (each works best for different words); otherwise just the text."""
    if not english_terms(text):
        return [text]
    return [with_english_terms(text), to_english_words(text)]
