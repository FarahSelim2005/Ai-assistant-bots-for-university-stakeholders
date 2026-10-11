"""Campus knowledge done in plain code (not by the language model):
- room codes in an answer (e.g. "M005") become map locations, if they follow the GIU
  numbering rules (ground floor 001-030, floors 1-4 numbered x01-x20);
- room codes in a question become a fact with their building and floor;
- places outside the buildings named in an answer get a walking link.
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
