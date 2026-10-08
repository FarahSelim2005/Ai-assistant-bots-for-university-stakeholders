"""Turn room codes in an answer (for example "M005" or "A312") into map locations.

This is plain code, not the language model: a room is only shown on the map if its
code appears in the answer and follows the GIU numbering rules (ground floor 001-030,
floors 1-4 numbered x01-x20). Must stay in line with data/raw/campus_buildings.md.
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
