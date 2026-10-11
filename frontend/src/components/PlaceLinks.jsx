// Walking links for places outside the buildings (gym, supermarket, courts...) that an
// answer mentions. The places come from the backend (app/campus.py, find_places).
import { placeWalkingUrl } from "../campusGeo.js";

export default function PlaceLinks({ places }) {
  const withPosition = places.filter((place) => placeWalkingUrl(place.key));
  if (withPosition.length === 0) return null;

  return (
    <div className="campus-map place-links">
      <div className="map-header">
        <span>📍 How to get there</span>
        <span className="muted">GIU campus</span>
      </div>
      <div className="place-buttons">
        {withPosition.map((place) => (
          <a key={place.key} href={placeWalkingUrl(place.key)} target="_blank" rel="noreferrer" className="walk-button">
            🚶 Walk me to the {place.name}
          </a>
        ))}
      </div>
    </div>
  );
}
