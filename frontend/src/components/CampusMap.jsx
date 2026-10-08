// Campus map shown under answers that mention rooms (e.g. "M005").
// The locations come from the backend (app/campus.py). The drawing follows the real
// GIU campus layout (traced from an aerial map): A top-left, S below A next to the
// road, M on the right. Keep it in line with the "Campus Layout and Directions"
// section of backend/data/raw/campus_buildings.md.
import { googleMapsWalkingUrl } from "../campusGeo.js";

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
const FLOORS = [4, 3, 2, 1, 0]; // drawn top to bottom
const FLOOR_LABELS = ["G", "1", "2", "3", "4"];
const GOOGLE_MAPS_URL =
  "https://www.google.com/maps/search/?api=1&query=German+International+University+GIU+New+Administrative+Capital";

export default function CampusMap({ locations }) {
  const buildings = [...new Set(locations.map((l) => l.building))];

  return (
    <div className="campus-map">
      <div className="map-header">
        <span>📍 How to get there</span>
        <span className="muted">GIU campus</span>
      </div>

      <div className="map-body">
        <svg viewBox="0 0 400 230" className="map-svg" role="img"
             aria-label={`Campus map highlighting building ${buildings.join(", ")}`}>
          {/* Landmarks around the buildings (not clickable, just for orientation) */}
          <rect x="170" y="8" width="66" height="50" rx="3" className="map-court" />
          <text x="203" y="37" textAnchor="middle" className="map-label-small light">Courts</text>
          <rect x="240" y="0" width="40" height="26" rx="3" className="map-court blue" />
          <rect x="312" y="88" width="44" height="34" rx="3" className="map-landmark" />
          <text x="334" y="109" textAnchor="middle" className="map-label-small">Food</text>

          {/* Road and car park along the south side */}
          <path d="M0 196 C 120 182, 260 168, 400 128 L 400 150 C 260 190, 120 204, 0 218 Z" className="map-road" />
          <text x="300" y="186" textAnchor="middle" className="map-label-small">Road &amp; car park</text>

          {/* North arrow */}
          <g transform="translate(378, 30)">
            <path d="M0 -14 L6 4 L0 0 L-6 4 Z" className="map-north" />
            <text y="16" textAnchor="middle" className="map-label-small">N</text>
          </g>

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
                {active && (
                  // Map pin above the highlighted building
                  <g transform={`translate(${b.x + b.width / 2}, ${b.y + 4})`}>
                    <path d="M0 0 C-9 -12 -9 -22 0 -24 C9 -22 9 -12 0 0 Z" className="map-pin" />
                    <circle cy="-16" r="3.5" fill="#fff" />
                  </g>
                )}
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
          <a href={GOOGLE_MAPS_URL} target="_blank" rel="noreferrer" className="maps-link">
            Directions to the GIU campus in Google Maps ↗
          </a>
        </div>
      </div>
    </div>
  );
}
