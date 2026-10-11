// Real GPS positions of the building entrances and of places on campus, used for the
// "Walk me there" links that open Google Maps walking directions from the user's location.

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

// [latitude, longitude] of places outside the buildings. Keys must match PLACES in
// backend/app/campus.py. Most come from Plus Codes the user copied from Google Maps;
// the tennis and basketball courts are estimated (no exact code yet).
export const PLACES = {
  supermarket: [30.004688, 31.701797], // 2P32+VPF
  gym: [dms(30, 0, 18.0), dms(31, 42, 6.0)],
  padel: [30.004387, 31.701484], // 2P32+QH5
  food_court: [dms(30, 0, 17.8), dms(31, 42, 8.3)],
  football: [30.005138, 31.701141], // 2P42+3F2
  tennis: [30.004645, 31.701079], // estimated from the aerial picture
  basketball: [30.005138, 31.700726], // estimated: ~40 m west of the football field
};

function walkingUrl([lat, lng]) {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat.toFixed(6)},${lng.toFixed(6)}&travelmode=walking`;
}

// Google Maps walking navigation (works in the app and in the browser).
export function googleMapsWalkingUrl(building) {
  return walkingUrl(ENTRANCES[building][0]);
}

export function placeWalkingUrl(placeKey) {
  return PLACES[placeKey] ? walkingUrl(PLACES[placeKey]) : null;
}
