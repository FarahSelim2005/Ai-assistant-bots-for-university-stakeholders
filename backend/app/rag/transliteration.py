"""English words written in Arabic letters ("فين بسكت بال؟" = "where is basketball?").

Egyptian students often write English campus words in Arabic letters. The embedding
model does not recognise these, so before searching, the English word is added to the
question (or put in its place).

Spelling varies a lot, mostly in the vowel letters: بادل / بدل / باديل, باسكت / بسكت,
كلينك / كلينيك. So words are compared by their "skeleton": letters normalised
(أ/إ/آ -> ا, ى -> ي, ة -> ه, no diacritics), "ال" / "وال" / "بال"... removed from the
front, and the vowel letters ا و ي removed after the first letter. "بادل" and "بدل"
both become "بدل".
"""
import re

# English term -> some ways people write it in Arabic letters. Other spellings that only
# differ in vowel letters are recognised automatically through the skeleton.
GLOSSARY = {
    "basketball": ["باسكت بول", "بسكتبول", "باسكت"],
    "football field": ["فوتبول فيلد"],
    "football": ["فوتبول", "فوت بول", "فوتبال"],
    "tennis court": ["تنس كورت"],
    "tennis": ["تنس"],
    "gym": ["جيم"],
    "supermarket": ["سوبر ماركت", "سوبرماركت", "ماركت"],
    "food court": ["فود كورت", "فودكورت"],
    "padel": ["بادل"],
    "clinic": ["كلينك"],
    "library": ["لايبراري", "لايبرري"],
    "student affairs": ["ستيودنت افيرز", "ستيودنت افيرس"],
    "admission office": ["ادميشن اوفيس"],
    "admission": ["ادميشن", "ادميشنز"],
    "German office": ["جيرمان اوفيس"],
    "German": ["جيرمان"],
    "office": ["اوفيس"],
    "AI lab": ["ايه اي لاب", "اي اي لاب"],
    "lab": ["لاب", "لابز"],
    "finance": ["فاينانس", "فينانس"],
    "academic coordinator": ["اكاديمك كوردينيتور"],
    "coordinator": ["كوردينيتور"],
    "research": ["ريسيرش"],
    "grant": ["جرانت"],
    "thesis": ["ثيسيس", "تيزيس"],
    "supervisor": ["سوبرفايزر", "سوبر فايزر"],
    "deadline": ["ديدلاين"],
    "tuition fees": ["تيوشن فيز"],
    "tuition": ["تيوشن"],
    "electronics": ["الكترونكس"],
    "building": ["بيلدنج"],
    "room": ["روم"],
    "floor": ["فلور"],
    # careers (Internship & Career agent)
    "CV": ["سي في", "السي في"],
    "resume": ["ريزيوم", "ريزومي"],
    "internship": ["انترنشيب", "انترنشبس"],
    "interview": ["انترفيو", "انترفيوز"],
    "LinkedIn": ["لينكد ان", "لينكدان"],
    "career fair": ["كارير فير"],
    "career center": ["كارير سنتر"],
    "career": ["كارير"],
    "skills": ["سكيلز", "سكيل"],
    # advising (Graduation & Advising agent)
    "IT": ["اي تي", "آي تي"],
    "advising": ["ادفايزنج", "ادفايزينج", "ادفيزنج"],
    "advisor": ["ادفايزر", "ادفيزر"],
    "probation": ["بروبيشن", "بروبيجن"],
    "memo": ["ميمو"],
    "clash": ["كلاش"],
    "electives": ["اليكتيف", "الكتيف", "اليكتيفز"],
    "makeup exam": ["ميك اب", "ميكاب"],
    "GPA": ["جي بي ايه", "جي بي اي"],
    "Bachelor thesis": ["باتشلر", "باتشلور"],
    # study programs and courses (Computer Science curriculum)
    "IT security": ["اي تي سيكيوريتي", "آي تي سيكيوريتي"],
    "security": ["سيكيوريتي", "سكيوريتي"],
    "data science": ["داتا ساينس", "داتا ساينز"],
    "software engineering": ["سوفتوير انجينيرنج", "سوفت وير انجينيرنج", "سوفتوير"],
    "media informatics": ["ميديا انفورماتكس", "ميديا انفورماتيكس", "ميديا"],
    "computer science": ["كمبيوتر ساينس", "كومبيوتر ساينس"],
    "semester": ["سيمستر", "سمستر"],
    "ECTS": ["اي سي تي اس"],
    "credit hours": ["كريدت اورز", "كريديت اورز", "كريدت"],
    "courses": ["كورسات", "كورسز"],
    "machine learning": ["ماشين ليرنينج", "ماشين ليرننج"],
    "big data": ["بيج داتا", "بج داتا"],
    "project management": ["بروجكت مانجمنت", "بروجيكت مانجمنت"],
    "databases": ["داتابيز", "داتا بيز", "داتابيس"],
    "programming": ["بروجرامنج", "بروجرامينج"],
    "operating systems": ["اوبريتنج سيستمز", "اوبرتنج سيستم"],
    "networks": ["نتوركس", "نتورك"],
    "computer graphics": ["كمبيوتر جرافيكس", "جرافيكس"],
    "cryptography": ["كريبتوجرافي", "كريبتو"],
    # Egyptian question words, so "فين بسكت بال" can also be searched as "where is basketball"
    "where is": ["فين"],
    "when": ["امتي"],
    "how": ["ازاي"],
}
QUESTION_WORDS = {"where is", "when", "how"}  # not campus terms: they never trigger a search variant alone

# Skeletons that are also everyday Arabic words: "بدل" = "instead of", "تنسى" = "forget".
# They only count when the question is about a place (see _looks_like_a_place).
AMBIGUOUS = {"بدل", "تنس"}
PLACE_CUES = {"فين", "ملعب", "كورت", "مكان", "اروح", "يروح", "نروح", "اوصل", "العب", "نلعب"}

_DIACRITICS = re.compile(r"[ً-ْـ]")  # harakat and tatweel
_PREFIXES = ("وال", "بال", "فال", "كال", "لل", "ال")


def normalize_arabic(text: str) -> str:
    text = _DIACRITICS.sub("", text)
    text = re.sub("[أإآ]", "ا", text)
    return text.replace("ى", "ي").replace("ة", "ه")


def _strip_prefix(word: str) -> tuple[str, bool]:
    """Remove "ال", "وال", "بال"... from the front; also say whether one was removed."""
    for prefix in _PREFIXES:
        if word.startswith(prefix) and len(word) - len(prefix) >= 2:
            return word[len(prefix):], True
    return word, False


def skeleton(word: str) -> str:
    """The word without its "ال" and without vowel letters after the first letter."""
    word, _ = _strip_prefix(normalize_arabic(word))
    return word[:1] + re.sub("[اوي]", "", word[1:])


# Every spelling as a tuple of word skeletons, longest phrases first, so that
# "فود كورت" is matched as "food court" before "كورت" alone could be.
_PHRASES = sorted(
    {(tuple(skeleton(w) for w in spelling.split()), english)
     for english, spellings in GLOSSARY.items() for spelling in spellings},
    key=lambda phrase: len(phrase[0]), reverse=True,
)


def _looks_like_a_place(words: list[str], had_article: bool) -> bool:
    return had_article or any(_strip_prefix(w)[0] in PLACE_CUES or w in PLACE_CUES for w in words)


def _matches(text: str) -> list[tuple[int, int, str]]:
    """(first word, number of words, English term) for every glossary word in the text."""
    words = re.findall(r"\w+", normalize_arabic(text))
    skeletons = [skeleton(w) for w in words]
    found, i = [], 0
    while i < len(words):
        for phrase, english in _PHRASES:
            n = len(phrase)
            if tuple(skeletons[i:i + n]) != phrase:
                continue
            had_article = _strip_prefix(words[i])[1]
            if n == 1 and phrase[0] in AMBIGUOUS and not _looks_like_a_place(words, had_article):
                continue
            found.append((i, n, english))
            i += n
            break
        else:
            i += 1
    return found


def english_terms(text: str) -> list[str]:
    """Campus terms written in Arabic letters in the text, e.g. ["basketball"]."""
    return list(dict.fromkeys(english for _, _, english in _matches(text) if english not in QUESTION_WORDS))


def with_english_terms(text: str) -> str:
    """The text plus the English terms it contains: "فين بسكت بال؟ (basketball)"."""
    terms = english_terms(text)
    return f"{text} ({', '.join(terms)})" if terms else text


def to_english_words(text: str) -> str:
    """The text with those words replaced by English: "فين basketball"."""
    words = re.findall(r"\w+", normalize_arabic(text))
    replaced = {i: (n, english) for i, n, english in _matches(text)}
    out, i = [], 0
    while i < len(words):
        if i in replaced:
            n, english = replaced[i]
            out.append(english)
            i += n
        else:
            out.append(words[i])
            i += 1
    return " ".join(out)


def search_variants(text: str) -> list[str]:
    """Ways to search for a question. With English words written in Arabic letters, both
    forms are searched (each works best for different words); otherwise just the text."""
    if not english_terms(text):
        return [text]
    return [with_english_terms(text), to_english_words(text)]
