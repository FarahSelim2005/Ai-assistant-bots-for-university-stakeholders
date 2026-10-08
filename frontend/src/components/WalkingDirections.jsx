// Walking directions to a building, like a mini Google Maps: your position (GPS, or a
// building you choose as the starting point), a dashed line to the nearest entrance of
// the target building, and the direction and distance, updated live as you walk.
import { useEffect, useState } from "react";
import {
  ENTRANCES, bearingDegrees, center, directionWord, distanceMeters,
  googleMapsWalkingUrl, nearestEntrance, toMeters,
} from "../campusGeo.js";

const ARRIVED_METERS = 15;      // close enough to the door to say "you've arrived"
const OFF_CAMPUS_METERS = 1500; // farther than this: use Google Maps instead
const MAP_WIDTH = 340;
const MAP_HEIGHT = 240;
const PADDING = 30;

export default function WalkingDirections({ building, buildingName, rooms, onClose }) {
  const [start, setStart] = useState("gps"); // "gps" or a building letter
  const [gps, setGps] = useState(null);      // { position: [lat, lng], accuracy }
  const [gpsError, setGpsError] = useState("");

  // Follow the user's position while "My location" is selected.
  useEffect(() => {
    if (start !== "gps") return undefined;
    if (!navigator.geolocation) {
      setGpsError("This browser cannot share your location. Choose a starting building instead.");
      return undefined;
    }
    setGpsError("");
    const watchId = navigator.geolocation.watchPosition(
      (pos) => setGps({ position: [pos.coords.latitude, pos.coords.longitude], accuracy: pos.coords.accuracy }),
      (err) => setGpsError(err.code === err.PERMISSION_DENIED
        ? "Location access was blocked. Allow it for this site, or choose a starting building."
        : "Your location is not available right now. Choose a starting building instead."),
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 20000 },
    );
    return () => navigator.geolocation.clearWatch(watchId);
  }, [start]);

  const from = start === "gps" ? gps?.position : nearestEntrance(start, center(ENTRANCES[building]));
  const door = nearestEntrance(building, from);
  const distance = from ? distanceMeters(from, door) : null;
  const offCampus = distance !== null && distance > OFF_CAMPUS_METERS;
  const arrived = distance !== null && distance <= ARRIVED_METERS;
  const floorText = rooms.map((r) => `${r.room} is on the ${r.floor_name.toLowerCase()}`).join(", ");

  return (
    <div className="walk" role="dialog" aria-label={`Walking directions to Building ${building}`}>
      <div className="walk-panel">
        <div className="walk-header">
          <div>
            <strong>🚶 To Building {building}</strong>
            <span className="muted"> · {buildingName}</span>
          </div>
          <button className="secondary" onClick={onClose}>Close</button>
        </div>

        <div className="walk-start">
          <span className="muted">Start from:</span>
          {["gps", ...Object.keys(ENTRANCES).filter((b) => b !== building)].map((option) => (
            <button key={option} className={start === option ? "active" : ""} onClick={() => setStart(option)}>
              {option === "gps" ? "📍 My location" : `Building ${option}`}
            </button>
          ))}
        </div>

        <div className="walk-instruction">
          {!from && !gpsError && <p>Finding your location…</p>}
          {!from && gpsError && <p className="error">{gpsError}</p>}
          {from && offCampus && (
            <p>You are {(distance / 1000).toFixed(1)} km away from campus. Use Google Maps to get here.</p>
          )}
          {from && !offCampus && arrived && (
            <p className="walk-big">✅ You've arrived at Building {building}. {floorText}.</p>
          )}
          {from && !offCampus && !arrived && (
            <p className="walk-big">
              Head <b>{directionWord(bearingDegrees(from, door))}</b> · <b>{Math.round(distance)} m</b>
              <span className="muted walk-sub">to the nearest entrance of Building {building}. Then: {floorText}.</span>
            </p>
          )}
          {start === "gps" && gps && gps.accuracy > 30 && !offCampus && (
            <p className="muted walk-sub">
              Your location is only accurate to about {Math.round(gps.accuracy)} m (laptops are often
              imprecise). For best results use a phone.
            </p>
          )}
        </div>

        {!offCampus && <WalkMap building={building} from={from} door={door} accuracy={start === "gps" ? gps?.accuracy : 0} />}

        <a href={googleMapsWalkingUrl(door)} target="_blank" rel="noreferrer" className="redirect-button walk-google">
          Open walking directions in Google Maps ↗
        </a>
      </div>
    </div>
  );
}

// North-up map in real proportions: all entrances, the user's position and the route line.
function WalkMap({ building, from, door, accuracy }) {
  const allDoors = Object.values(ENTRANCES).flat();
  const origin = center(allDoors);
  const points = [...allDoors, ...(from ? [from] : [])].map((p) => toMeters(p, origin));

  // Fit everything into the drawing: one scale for x and y keeps distances true.
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const spanX = Math.max(...xs) - Math.min(...xs) || 1;
  const spanY = Math.max(...ys) - Math.min(...ys) || 1;
  const scale = Math.min((MAP_WIDTH - 2 * PADDING) / spanX, (MAP_HEIGHT - 2 * PADDING) / spanY);
  const midX = (Math.max(...xs) + Math.min(...xs)) / 2;
  const midY = (Math.max(...ys) + Math.min(...ys)) / 2;
  const toSvg = (latLng) => {
    const [x, y] = toMeters(latLng, origin);
    return [MAP_WIDTH / 2 + (x - midX) * scale, MAP_HEIGHT / 2 - (y - midY) * scale]; // north up
  };

  const [doorX, doorY] = toSvg(door);
  const user = from ? toSvg(from) : null;

  return (
    <svg viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`} className="walk-map" role="img" aria-label="Route map">
      {Object.entries(ENTRANCES).map(([letter, doors]) => {
        const [cx, cy] = toSvg(center(doors));
        const target = letter === building;
        return (
          <g key={letter}>
            <circle cx={cx} cy={cy} r="20" className={target ? "walk-building target" : "walk-building"} />
            <text x={cx} y={cy + 6} textAnchor="middle" className="walk-letter">{letter}</text>
            {doors.map((d, i) => {
              const [x, y] = toSvg(d);
              return <rect key={i} x={x - 3} y={y - 3} width="6" height="6" className="walk-door" />;
            })}
          </g>
        );
      })}

      {user && (
        <>
          <line x1={user[0]} y1={user[1]} x2={doorX} y2={doorY} className="walk-route" />
          {accuracy > 0 && <circle cx={user[0]} cy={user[1]} r={Math.min(accuracy * scale, 60)} className="walk-accuracy" />}
          <circle cx={user[0]} cy={user[1]} r="7" className="walk-user" />
        </>
      )}
      <circle cx={doorX} cy={doorY} r="6" className="walk-target-door" />

      <g transform={`translate(${MAP_WIDTH - 18}, 24)`}>
        <path d="M0 -12 L5 4 L0 0 L-5 4 Z" className="map-north" />
        <text y="15" textAnchor="middle" className="map-label-small">N</text>
      </g>
    </svg>
  );
}
