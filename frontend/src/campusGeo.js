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
// backend/app/campus.py. Taken from each place's own Google Maps pin (its share link),
// except the food court, which has no pin (coordinates copied by the user).
export const PLACES = {
  supermarket: [30.0050804, 31.7015537], // GIU Supermarket
  gym: [30.0050087, 31.7016298],         // الجيم
  padel: [30.0046121, 31.7015252],       // GoPadel
  food_court: [dms(30, 0, 17.8), dms(31, 42, 8.3)],
  football: [30.0050833, 31.7012533],    // GIU Football Field
  tennis: [30.004766, 31.700971],        // GIU Tennis Court
  basketball: [30.0045601, 31.7005281],  // GIU Basketball Court
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
