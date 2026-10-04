// Schematic campus map shown under answers that mention rooms (e.g. "M005").
// The locations come from the backend (app/campus.py). The layout below must match
// the "Campus Layout and Directions" section of backend/data/raw/campus_buildings.md;
// replace it with the official GIU campus map when available.

const BUILDINGS = {
  A: { x: 20, y: 70, width: 90, height: 80, direction: "cross the central square and turn left to Building A" },
  M: { x: 135, y: 15, width: 110, height: 60, direction: "walk straight across the central square to Building M" },
  S: { x: 270, y: 70, width: 90, height: 80, direction: "cross the central square and turn right to Building S" },
};
const FLOORS = [4, 3, 2, 1, 0]; // drawn top to bottom
const FLOOR_LABELS = ["G", "1", "2", "3", "4"];
const GOOGLE_MAPS_URL =
  "https://www.google.com/maps/search/?api=1&query=German+International+University+New+Administrative+Capital";

export default function CampusMap({ locations }) {
  const buildings = [...new Set(locations.map((l) => l.building))];

  return (
    <div className="campus-map">
      <div className="map-header">
        <span>📍 How to get there</span>
        <span className="muted">Schematic map</span>
      </div>

      <div className="map-body">
        <svg viewBox="0 0 380 230" className="map-svg" role="img"
             aria-label={`Campus map highlighting building ${buildings.join(", ")}`}>
          {/* Central square and path from the gate */}
          <rect x="125" y="95" width="130" height="80" rx="8" className="map-square" />
          <text x="190" y="140" className="map-label-small" textAnchor="middle">Central square</text>
          <rect x="178" y="175" width="24" height="30" className="map-path" />
          <text x="190" y="222" className="map-label-small" textAnchor="middle">Main gate ▲ you enter here</text>

          {Object.entries(BUILDINGS).map(([letter, b]) => {
            const active = buildings.includes(letter);
            return (
              <g key={letter}>
                <rect x={b.x} y={b.y} width={b.width} height={b.height} rx="6"
                      className={active ? "map-building active" : "map-building"} />
                <text x={b.x + b.width / 2} y={b.y + b.height / 2 + 8} textAnchor="middle"
                      className={active ? "map-letter active" : "map-letter"}>
                  {letter}
                </text>
                {active && (
                  // Map pin above the highlighted building
                  <g transform={`translate(${b.x + b.width / 2}, ${b.y - 2})`}>
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
                    <li>From the main gate, {BUILDINGS[letter].direction}.</li>
                    {here.map((l) => (
                      <li key={l.room}>
                        {l.floor === 0
                          ? <>Room <b>{l.room}</b> is on the <b>ground floor</b>.</>
                          : <>Take the stairs or elevator to the <b>{l.floor_name.toLowerCase()}</b> for room <b>{l.room}</b>.</>}
                      </li>
                    ))}
                  </ol>
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
