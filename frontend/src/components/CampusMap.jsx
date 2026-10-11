// Campus map shown under answers that mention rooms (e.g. "M005") or places outside
// the buildings (gym, supermarket, courts...). Both come from the backend
// (app/campus.py). The drawing follows the real GIU campus layout, traced from an
// aerial map: A top-left, S below A next to the road, M on the right, and the sports
// and food area north-east of M. Keep it in line with the "Campus Layout and
// Directions" and place sections of backend/data/raw/campus_buildings.md.
import { googleMapsWalkingUrl, placeWalkingUrl } from "../campusGeo.js";

const BUILDINGS = {
  A: {
    x: 66, y: 22, width: 98, height: 60,
    direction: "walk past Building S on the left; Building A is behind it, further from the road",
  },
  S: {
    x: 45, y: 92, width: 112, height: 64,
    direction: "Building S is on the left, the building closest to the road (next to the swimming pool)",
  },
  M: {
    x: 176, y: 68, width: 102, height: 88,
    direction: "Building M is the large building on the right, the main GIU building with the CIB ATM",
  },
};

// Places outside the buildings: where they are drawn, how they look, and how to get
// there. Keys must match PLACES in backend/app/campus.py and frontend/src/campusGeo.js.
const PLACES = {
  football: {
    x: 272, y: -68, width: 58, height: 32, kind: "grass", label: "Football", icon: "⚽",
    steps: ["From Building M, walk about 140 m north, past the tennis court.",
            "The football field is on the other side of the supermarket."],
  },
  gym: {
    x: 338, y: -68, width: 34, height: 18, kind: "landmark", label: "Gym", icon: "🏋️",
    steps: ["From Building M, walk about 145 m north-east.",
            "The gym is next to the supermarket, behind the padel court."],
  },
  supermarket: {
    x: 340, y: -44, width: 40, height: 22, kind: "landmark", label: "Market", icon: "🛒",
    steps: ["From Building M, walk about 130 m north-east.",
            "The supermarket is next to the gym, behind the padel court."],
  },
  padel: {
    x: 330, y: 8, width: 34, height: 28, kind: "grass", label: "Padel", icon: "🎾",
    steps: ["From Building M, walk about 85 m north-east.",
            "The padel court is in front of the supermarket and the gym."],
  },
  food_court: {
    x: 400, y: -30, width: 56, height: 50, kind: "grass", label: "Food", icon: "🍔",
    steps: ["From Building M, walk about 185 m north-east.",
            "The food court is in front of the padel court, with restaurants and cafes."],
  },
  tennis: {
    x: 244, y: -2, width: 38, height: 26, kind: "court blue", label: "Tennis", icon: "🎾",
    steps: ["From Building M, walk about 80 m north.",
            "The tennis court is between Building A and Building M, next to the red sports court."],
  },
  basketball: {
    x: 316, y: 74, width: 34, height: 22, kind: "court", label: "Basket", icon: "🏀",
    steps: ["From Building M, walk about 70 m east.",
            "The basketball court is just east of Building M."],
  },
};

const FLOORS = [4, 3, 2, 1, 0]; // drawn top to bottom
const FLOOR_LABELS = ["G", "1", "2", "3", "4"];
const GOOGLE_MAPS_URL =
  "https://www.google.com/maps/search/?api=1&query=German+International+University+GIU+New+Administrative+Capital";

// Map pin drawn above a highlighted building or place.
function Pin({ x, y }) {
  return (
    <g transform={`translate(${x}, ${y})`}>
      <path d="M0 0 C-9 -12 -9 -22 0 -24 C9 -22 9 -12 0 0 Z" className="map-pin" />
      <circle cy="-16" r="3.5" fill="#fff" />
    </g>
  );
}

export default function CampusMap({ locations = [], places = [] }) {
  const buildings = [...new Set(locations.map((l) => l.building))];
  const placeKeys = places.map((p) => p.key).filter((key) => PLACES[key]);
  const highlighted = [...buildings.map((b) => `building ${b}`), ...placeKeys];

  return (
    <div className="campus-map">
      <div className="map-header">
        <span>📍 How to get there</span>
        <span className="muted">GIU campus</span>
      </div>

      <div className="map-body">
        <svg viewBox="0 -96 470 324" className="map-svg" role="img"
             aria-label={`Campus map highlighting ${highlighted.join(", ")}`}>
          {/* Red sports court between A and M (not a place of its own, just for orientation) */}
          <rect x="170" y="8" width="66" height="50" rx="3" className="map-court" />
          <text x="203" y="37" textAnchor="middle" className="map-label-small light">Courts</text>

          {/* Road and car park along the south-east side */}
          <path d="M0 202 C 150 196, 300 178, 470 100 L 470 124 C 300 202, 150 220, 0 224 Z" className="map-road" />
          <text x="120" y="192" textAnchor="middle" className="map-label-small">Road &amp; car park</text>

          {/* North arrow */}
          <g transform="translate(452, -74)">
            <path d="M0 -14 L6 4 L0 0 L-6 4 Z" className="map-north" />
            <text y="16" textAnchor="middle" className="map-label-small">N</text>
          </g>

          {Object.entries(PLACES).map(([key, p]) => {
            const active = placeKeys.includes(key);
            return (
              <g key={key}>
                <rect x={p.x} y={p.y} width={p.width} height={p.height} rx="3"
                      className={active ? `map-place map-${p.kind} active` : `map-place map-${p.kind}`} />
                <text x={p.x + p.width / 2} y={p.y + p.height / 2 + 3} textAnchor="middle"
                      className={active || p.kind.startsWith("court") ? "map-label-small light" : "map-label-small"}>
                  {p.label}
                </text>
                {active && <Pin x={p.x + p.width / 2} y={p.y + 2} />}
              </g>
            );
          })}

          {Object.entries(BUILDINGS).map(([letter, b]) => {
            const active = buildings.includes(letter);
            return (
              <g key={letter}>
                <rect x={b.x} y={b.y} width={b.width} height={b.height} rx="5"
                      className={active ? "map-building active" : "map-building"} />
                <text x={b.x + b.width / 2} y={b.y + b.height / 2 + 9} textAnchor="middle"
                      className={active ? "map-letter active" : "map-letter"}>
                  {letter}
                </text>
                {active && <Pin x={b.x + b.width / 2} y={b.y + 4} />}
              </g>
            );
          })}
        </svg>

        <div className="map-details">
          {buildings.map((letter) => {
            const here = locations.filter((l) => l.building === letter);
            const floors = here.map((l) => l.floor);
            return (
              <div key={letter} className="map-building-info">
                <div className="floor-stack" aria-label="Floors">
                  {FLOORS.map((floor) => (
                    <div key={floor} className={floors.includes(floor) ? "floor active" : "floor"}>
                      {FLOOR_LABELS[floor]}
                    </div>
                  ))}
                </div>
                <div>
                  <strong>Building {letter}</strong>
                  <span className="muted"> · {here[0].building_name}</span>
                  <ol className="directions">
                    <li>From the car park, {BUILDINGS[letter].direction}.</li>
                    {here.map((l) => (
                      <li key={l.room}>
                        {l.floor === 0
                          ? <>Room <b>{l.room}</b> is on the <b>ground floor</b>.</>
                          : <>Take the stairs or elevator to the <b>{l.floor_name.toLowerCase()}</b> for room <b>{l.room}</b>.</>}
                      </li>
                    ))}
                  </ol>
                  <a href={googleMapsWalkingUrl(letter)} target="_blank" rel="noreferrer" className="walk-button">
                    🚶 Walk me to Building {letter}
                  </a>
                </div>
              </div>
            );
          })}

          {places.filter((place) => PLACES[place.key]).map((place) => (
            <div key={place.key} className="map-building-info">
              <div className="place-icon" aria-hidden="true">{PLACES[place.key].icon}</div>
              <div>
                <strong>{place.name}</strong>
                <span className="muted"> · outdoors</span>
                <ol className="directions">
                  <li>From the car park, go towards Building M, the large building on the right.</li>
                  {PLACES[place.key].steps.map((step) => <li key={step}>{step}</li>)}
                </ol>
                <a href={placeWalkingUrl(place.key)} target="_blank" rel="noreferrer" className="walk-button">
                  🚶 Walk me to the {place.name}
                </a>
              </div>
            </div>
          ))}

          <a href={GOOGLE_MAPS_URL} target="_blank" rel="noreferrer" className="maps-link">
            Directions to the GIU campus in Google Maps ↗
          </a>
        </div>
      </div>
    </div>
  );
}
