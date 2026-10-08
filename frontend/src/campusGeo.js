// Real GPS positions of the building entrances and the small amount of maths needed
// for walking directions (distance, direction, nearest door). No map library needed:
// over a campus a few hundred metres wide the Earth can be treated as flat.

// Degrees, minutes, seconds (as copied from Google Maps) -> decimal degrees.
function dms(degrees, minutes, seconds) {
  return degrees + minutes / 60 + seconds / 3600;
}

// [latitude, longitude] of every entrance, per building.
export const ENTRANCES = {
  A: [
    [dms(30, 0, 16.1), dms(31, 42, 0.8)],
    [dms(30, 0, 15.8), dms(31, 41, 59.5)],
    [dms(30, 0, 16.7), dms(31, 42, 0.2)],
  ],
  M: [
    [dms(30, 0, 13.8), dms(31, 42, 2.9)],
    [dms(30, 0, 14.6), dms(31, 42, 2.7)],
  ],
  S: [[dms(30, 0, 13.5), dms(31, 41, 59.1)]],
};

const EARTH_RADIUS_M = 6371000;
const toRad = (degrees) => (degrees * Math.PI) / 180;

// Position in metres (x = east, y = north) relative to `origin`.
export function toMeters([lat, lng], [originLat, originLng]) {
  return [
    toRad(lng - originLng) * EARTH_RADIUS_M * Math.cos(toRad(originLat)),
    toRad(lat - originLat) * EARTH_RADIUS_M,
  ];
}

export function distanceMeters(from, to) {
  const [x, y] = toMeters(to, from);
  return Math.hypot(x, y);
}

// Compass direction from `from` to `to` in degrees (0 = north, 90 = east).
export function bearingDegrees(from, to) {
  const [x, y] = toMeters(to, from);
  return (Math.atan2(x, y) * 180 / Math.PI + 360) % 360;
}

const DIRECTION_WORDS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"];
export function directionWord(bearing) {
  return DIRECTION_WORDS[Math.round(bearing / 45) % 8];
}

export function center(points) {
  return [
    points.reduce((sum, p) => sum + p[0], 0) / points.length,
    points.reduce((sum, p) => sum + p[1], 0) / points.length,
  ];
}

// The entrance of `building` closest to `from` (or its first entrance if `from` is unknown).
export function nearestEntrance(building, from) {
  const doors = ENTRANCES[building];
  if (!from) return doors[0];
  return doors.reduce((best, door) => (distanceMeters(from, door) < distanceMeters(from, best) ? door : best));
}

// Google Maps walking navigation to a point (works in the app and in the browser).
export function googleMapsWalkingUrl([lat, lng]) {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat.toFixed(6)},${lng.toFixed(6)}&travelmode=walking`;
}
