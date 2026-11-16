"""Campus knowledge done in plain code (not by the language model):
- room codes in an answer (e.g. "M005") become map locations, if they follow the GIU
  numbering rules (ground floor 001-030, floors 1-4 numbered x01-x20);
- room codes in a question become a fact with their building and floor;
- places outside the buildings named in an answer get a walking link;
- buildings asked about ("where is the M", "building S", "مبنى A") are shown on the map.
Must stay in line with data/raw/campus_buildings.md.
"""
import re
from dataclasses import dataclass

BUILDINGS = {
    "A": "Academic Building",
    "M": "Main Administration Building",
    "S": "Student Services Building",
}
FLOOR_NAMES = ["Ground floor", "1st floor", "2nd floor", "3rd floor", "4th floor"]
# Not part of a longer Latin word or number; Arabic letters right next to the code
# are allowed (e.g. "الM005").
ROOM_PATTERN = re.compile(r"(?<![A-Za-z0-9])([AMS])(\d)(\d{2})(?![A-Za-z0-9])")
MAX_LOCATIONS = 4  # keep the map readable when an answer lists many rooms


@dataclass
class Location:
    room: str
    building: str
    building_name: str
    floor: int
    floor_name: str


def is_valid_room(floor: int, number: int) -> bool:
    if floor == 0:
        return 1 <= number <= 30
    return 1 <= floor <= 4 and 1 <= number <= 20


def find_locations(text: str) -> list[Location]:
    """Valid room codes mentioned in the text, in order of appearance, without duplicates."""
    found: dict[str, Location] = {}
    for building, floor_digit, number in ROOM_PATTERN.findall(text):
        room = f"{building}{floor_digit}{number}"
        floor = int(floor_digit)
        if room not in found and is_valid_room(floor, int(number)):
            found[room] = Location(room, building, BUILDINGS[building], floor, FLOOR_NAMES[floor])
    return list(found.values())[:MAX_LOCATIONS]


# --- Rooms mentioned in a QUESTION -------------------------------------------------
# Users may type or say "a107", "A 107" or "A-107", so this pattern is more forgiving
# than the one used on answers.
QUESTION_ROOM_PATTERN = re.compile(r"(?<![A-Za-z0-9])([AMS])[\s-]?(\d)(\d{2})(?![A-Za-z0-9])", re.IGNORECASE)


def rooms_in_question(question: str) -> list[Location]:
    """Valid room codes the user asks about, normalised to e.g. "A107"."""
    rooms = [f"{b.upper()}{f}{n}" for b, f, n in QUESTION_ROOM_PATTERN.findall(question)]
    return find_locations(" ".join(rooms))


def room_facts(locations: list[Location]) -> str:
    """Building and floor of each room, worked out from the numbering rules. Given to the
    model as reliable context, so it can answer "which floor is A107 on?" for any room."""
    return " ".join(
        f"Room {l.room} is in Building {l.building} ({l.building_name}), on the {l.floor_name.lower()}."
        for l in locations
    )


# --- Places outside the buildings ----------------------------------------------------
@dataclass(frozen=True)
class Place:
    key: str                  # must match PLACES in frontend/src/campusGeo.js
    name: str
    keywords: tuple[str, ...]  # words in an answer (English or Arabic) that mean this place


PLACES = [
    Place("supermarket", "GIU Supermarket", ("supermarket", "سوبر ماركت", "سوبرماركت")),
    Place("gym", "Gym", ("gym", "الجيم", "جيم")),
    Place("padel", "Padel court", ("padel", "بادل")),
    Place("food_court", "Food court", ("food court", "فود كورت", "المطاعم")),
    Place("football", "Football field", ("football", "ملعب الكورة", "كرة القدم")),
    Place("tennis", "Tennis court", ("tennis", "تنس")),
    Place("basketball", "Basketball court", ("basketball", "باسكت", "كرة السلة")),
]


def find_places(text: str) -> list[Place]:
    """Places outside the buildings that the answer talks about (for walking links)."""
    lower = text.lower()
    return [place for place in PLACES if any(word in lower for word in place.keywords)]


# --- Buildings asked about -----------------------------------------------------------
# "building M", "bldg S", "مبنى A" / "مبنى ام"; "where is the M?", "where is S" (a letter
# alone at the end of a question). Arabic letter names: ايه/اي = A, ام = M, اس = S.
ARABIC_LETTERS = {"ايه": "A", "اي": "A", "ام": "M", "إم": "M", "اس": "S", "إس": "S"}
BUILDING_WORD = re.compile(r"\b(?:building|bldg|block)\s*([ams])\b|"
                           r"(?:مبنى|مبني|المبنى|بلوك)\s*(a|m|s|ايه|اي|إم|ام|إس|اس)(?![\w])", re.IGNORECASE)
LETTER_AT_END = re.compile(r"\b(?:where|wher|fin)\b.*?\b(?:the\s+)?([ams])\s*[?.!]*\s*$|"
                           r"(?:فين|وين)\s+(?:ال)?(a|m|s)\s*[?؟.!]*\s*$", re.IGNORECASE)
WHERE_WORDS = re.compile(r"\b(where|location|located|directions?)\b|فين|وين|مكان", re.IGNORECASE)
ANSWER_BUILDING = re.compile(r"\bBuilding\s+([AMS])\b")


def buildings_asked(question: str, answer: str = "") -> list[str]:
    """Letters of the buildings a question asks about (to show them on the map). A "where"
    question naming no letter ("where is the main administration building?") uses the one
    building the answer is about."""
    letters = []
    for match in list(BUILDING_WORD.finditer(question)) + list(LETTER_AT_END.finditer(question)):
        value = next(group for group in match.groups() if group)
        letters.append(ARABIC_LETTERS.get(value, value.upper()))
    if not letters and WHERE_WORDS.search(question):
        in_answer = list(dict.fromkeys(ANSWER_BUILDING.findall(answer)))
        letters = in_answer[:1]
    return list(dict.fromkeys(letters))


# --- Other universities' campuses ----------------------------------------------------
# GIU's campus above is fixed in code. Every other university draws its own in the admin
# (tenants.campus, migration 011): buildings with a code ("B"), a name and a number of floors,
# and outdoor places. Room codes follow one simple rule: the building's code, the floor
# (0 = ground floor) and a two-digit number, e.g. B204 = Building B, 2nd floor.

def ordinal_floor(floor: int) -> str:
    if floor == 0:
        return "Ground floor"
    suffix = "th" if 10 <= floor % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(floor % 10, "th")
    return f"{floor}{suffix} floor"


class UniversityCampus:
    """A university's own buildings and places (tenants.campus), with the same questions
    answered as for GIU: rooms in an answer or a question, places, buildings asked about."""

    def __init__(self, campus: dict):
        self.buildings = {b["code"]: b for b in campus.get("buildings", [])}
        self.places = [Place(p["key"], p["name"], tuple(w.lower() for w in [p["name"], *p.get("words", [])] if w))
                       for p in campus.get("places", [])]
        codes = "|".join(sorted(map(re.escape, self.buildings), key=len, reverse=True)) or "(?!)"
        self.room_pattern = re.compile(rf"(?<![A-Za-z0-9])({codes})(\d)(\d{{2}})(?![A-Za-z0-9])")
        self.question_room_pattern = re.compile(rf"(?<![A-Za-z0-9])({codes})[\s-]?(\d)(\d{{2}})(?![A-Za-z0-9])",
                                                re.IGNORECASE)
        self.building_word = re.compile(rf"\b(?:building|bldg|block)\s*({codes})\b|(?:مبنى|مبني|المبنى|بلوك)\s*({codes})(?![\w])",
                                        re.IGNORECASE)
        self.letter_at_end = re.compile(rf"\b(?:where|wher|fin)\b.*?\b(?:the\s+)?({codes})\s*[?.!]*\s*$|"
                                        rf"(?:فين|وين)\s+(?:ال)?({codes})\s*[?؟.!]*\s*$", re.IGNORECASE)
        self.answer_building = re.compile(rf"\bBuilding\s+({codes})\b")

    @classmethod
    def of(cls, campus: dict | None) -> "UniversityCampus | None":
        """The campus, or None when the university has not added a building or place yet."""
        if not campus or not (campus.get("buildings") or campus.get("places")):
            return None
        return cls(campus)

    def code(self, text: str) -> str | None:
        """The building code as saved ("b" -> "B"), or None."""
        return next((code for code in self.buildings if code.lower() == text.lower()), None)

    def location(self, code: str, floor: int, number: int) -> Location | None:
        building = self.buildings.get(code)
        if building is None or floor > int(building.get("floors", 0)) or number < 1:
            return None
        return Location(f"{code}{floor}{number:02d}", code, building["name"], floor, ordinal_floor(floor))

    def find_locations(self, text: str) -> list[Location]:
        found: dict[str, Location] = {}
        for code, floor, number in self.room_pattern.findall(text):
            location = self.location(code, int(floor), int(number))
            if location and location.room not in found:
                found[location.room] = location
        return list(found.values())[:MAX_LOCATIONS]

    def rooms_in_question(self, question: str) -> list[Location]:
        rooms = [f"{self.code(c)}{f}{n}" for c, f, n in self.question_room_pattern.findall(question)]
        return self.find_locations(" ".join(rooms))

    def find_places(self, text: str) -> list[Place]:
        lower = text.lower()
        return [place for place in self.places if any(word in lower for word in place.keywords)]

    def buildings_asked(self, question: str, answer: str = "") -> list[str]:
        codes = []
        for match in list(self.building_word.finditer(question)) + list(self.letter_at_end.finditer(question)):
            codes.append(self.code(next(group for group in match.groups() if group)))
        if not codes and WHERE_WORDS.search(question):
            lower = question.lower()
            codes = [code for code, b in self.buildings.items() if b["name"].lower() in lower][:1]
            if not codes:
                codes = list(dict.fromkeys(self.code(c) for c in self.answer_building.findall(answer)))[:1]
        return [code for code in dict.fromkeys(codes) if code]
