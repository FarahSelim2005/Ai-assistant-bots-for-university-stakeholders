// Real GPS positions of the building entrances, used for the "Walk me there" link that
// opens Google Maps walking directions (Google Maps starts from the user's location).

// Degrees, minutes, seconds (as copied from Google Maps) -> decimal degrees.
function dms(degrees, minutes, seconds) {
  return degrees + minutes / 60 + seconds / 3600;
}

// [latitude, longitude] of every entrance, per building. The first one is used for the link.
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

// Google Maps walking navigation to a building (works in the app and in the browser).
export function googleMapsWalkingUrl(building) {
  const [lat, lng] = ENTRANCES[building][0];
  return `https://www.google.com/maps/dir/?api=1&destination=${lat.toFixed(6)},${lng.toFixed(6)}&travelmode=walking`;
}
