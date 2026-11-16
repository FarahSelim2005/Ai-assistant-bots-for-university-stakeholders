// The campus map of a university other than GIU, from what its admin added under an
// assistant's "Campus map" skill (GET /tenant's campus): its campus picture with a pin on the
// buildings and places an answer is about, the floors of the rooms, and "Walk me there" links
// from the entrances' locations. GIU's built-in map is CampusMap.jsx.
import { API_URL } from "../api.js";
import { walkingUrlTo } from "../campusGeo.js";

const hasSpot = (item) => item?.x != null && item?.y != null;

export default function OwnCampusMap({ campus, locations = [], places = [], askedBuildings = [] }) {
  const byCode = Object.fromEntries(campus.buildings.map((b) => [b.code, b]));
  const codes = [...new Set([...locations.map((l) => l.building), ...askedBuildings.map((b) => b.letter)])]
    .filter((code) => byCode[code]);
  const shownPlaces = places.map((p) => campus.places.find((x) => x.key === p.key)).filter(Boolean);
  const pins = [...codes.map((code) => byCode[code]), ...shownPlaces].filter(hasSpot);
  if (!codes.length && !shownPlaces.length) return null;

  return (
    <div className="campus-map">
      <div className="map-header">
        <span>📍 How to get there</span>
      </div>
      <div className={campus.image_url ? "map-body" : "map-body single"}>
        {campus.image_url && (
          <div className="own-map">
            <img src={`${API_URL}${campus.image_url}`} alt="Campus map" />
            {campus.buildings.filter(hasSpot).map((b) => (
              <span key={b.code} className={codes.includes(b.code) ? "own-map-tag active" : "own-map-tag"}
                    style={{ left: `${b.x * 100}%`, top: `${b.y * 100}%` }}>{b.code}</span>
            ))}
            {pins.map((p) => (
              <svg key={p.code ?? p.key} className="own-map-pin" viewBox="-10 -26 20 28" aria-hidden="true"
                   style={{ left: `${p.x * 100}%`, top: `${p.y * 100}%` }}>
                <path d="M0 0 C-9 -12 -9 -22 0 -24 C9 -22 9 -12 0 0 Z" className="map-pin" />
                <circle cy="-16" r="3.5" fill="#fff" />
              </svg>
            ))}
          </div>
        )}

        <div className="map-details">
          {codes.map((code) => {
            const building = byCode[code];
            const here = locations.filter((l) => l.building === code);
            const floors = Array.from({ length: (building.floors ?? 0) + 1 }, (_, i) => building.floors - i);
            const walk = walkingUrlTo(building.lat, building.lng);
            return (
              <div key={code} className="map-building-info">
                <div className="floor-stack" aria-label="Floors">
                  {floors.map((floor) => (
                    <div key={floor} className={here.some((l) => l.floor === floor) ? "floor active" : "floor"}>
                      {floor === 0 ? "G" : floor}
                    </div>
                  ))}
                </div>
                <div>
                  <strong>Building {code}</strong>
                  <span className="muted"> · {building.name}</span>
                  {here.length > 0 && (
                    <ol className="directions">
                      {here.map((l) => (
                        <li key={l.room}>
                          {l.floor === 0
                            ? <>Room <b>{l.room}</b> is on the <b>ground floor</b>.</>
                            : <>Take the stairs or elevator to the <b>{l.floor_name.toLowerCase()}</b> for room <b>{l.room}</b>.</>}
                        </li>
                      ))}
                    </ol>
                  )}
                  {walk && <a href={walk} target="_blank" rel="noreferrer" className="walk-button">🚶 Walk me to Building {code}</a>}
                </div>
              </div>
            );
          })}

          {shownPlaces.map((place) => {
            const walk = walkingUrlTo(place.lat, place.lng);
            return (
              <div key={place.key} className="map-building-info">
                <div className="place-icon" aria-hidden="true">📍</div>
                <div>
                  <strong>{place.name}</strong>
                  <span className="muted"> · outdoors</span>
                  {walk && <div><a href={walk} target="_blank" rel="noreferrer" className="walk-button">🚶 Walk me to the {place.name}</a></div>}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
