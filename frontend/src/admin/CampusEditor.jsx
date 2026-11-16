// The university's campus map, under an assistant's "Campus map" skill (AssistantsPage): a
// picture of the campus, its buildings (code, name, floors) and outdoor places, each placed on
// the picture with a click and optionally given its Google Maps location for "Walk me there".
// Saved for the whole university (PUT /admin/campus): every assistant with the skill uses it.
// GIU's campus map is built in.
import { useEffect, useState } from "react";
import { API_URL } from "../api.js";
import { request } from "./api.js";

const MAX_IMAGE_BYTES = 3 * 1024 * 1024;

// "30.0043, 31.7008", or a Google Maps link (".../@30.0043,31.7008,17z" or "!3d30.0043!4d31.7008")
function parseLocation(text) {
  const t = text.trim();
  if (!t) return { lat: null, lng: null };
  const match = t.match(/!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/) || t.match(/(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)/);
  if (!match) return null;
  const [lat, lng] = [Number(match[1]), Number(match[2])];
  return Math.abs(lat) <= 90 && Math.abs(lng) <= 180 ? { lat, lng } : null;
}
const locationText = (item) => (item.lat != null && item.lng != null ? `${item.lat}, ${item.lng}` : "");

const toRows = (campus) => ({
  buildings: campus.buildings.map((b) => ({ ...b, where: locationText(b) })),
  places: campus.places.map((p) => ({ ...p, words: (p.words ?? []).join(", "), where: locationText(p) })),
});

export default function CampusEditor({ call }) {
  const [campus, setCampus] = useState(null); // as saved
  const [rows, setRows] = useState(null);     // as edited
  const [image, setImage] = useState(null);   // a new picture (data URL), "" = removed, null = unchanged
  const [placing, setPlacing] = useState(null); // ["buildings" | "places", index]: the next click on the picture places it
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    call((token) => request("/admin/campus", { token }))
      .then((data) => { setCampus(data); setRows(toRows(data)); })
      .catch((err) => setError(`Could not load the campus: ${err.message}`));
  }, []);

  if (error && !campus) return <p className="error">{error}</p>;
  if (!campus || !rows) return <p className="note">Loading the campus…</p>;
  if (campus.built_in) return <p className="note">This university’s campus map is built in.</p>;

  const picture = image === null ? (campus.image_url ? `${API_URL}${campus.image_url}` : "") : image;
  const dirty = image !== null || JSON.stringify(rows) !== JSON.stringify(toRows(campus));
  const change = (list, index, key) => (e) => setRows((r) => ({
    ...r, [list]: r[list].map((item, i) => (i === index ? { ...item, [key]: e.target.value } : item)),
  }));
  const add = (list, item) => setRows((r) => ({ ...r, [list]: [...r[list], item] }));
  const remove = (list, index) => {
    setPlacing(null);
    setRows((r) => ({ ...r, [list]: r[list].filter((_, i) => i !== index) }));
  };

  function pickImage(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) return setError("Choose a PNG, JPEG or WebP picture.");
    if (file.size > MAX_IMAGE_BYTES) return setError("The picture must be smaller than 3 MB.");
    const reader = new FileReader();
    reader.onload = () => { setImage(reader.result); setError(""); };
    reader.readAsDataURL(file);
  }

  function place(e) {
    if (!placing) return;
    const box = e.currentTarget.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width));
    const y = Math.min(1, Math.max(0, (e.clientY - box.top) / box.height));
    const [list, index] = placing;
    setRows((r) => ({ ...r, [list]: r[list].map((item, i) => (i === index ? { ...item, x: +x.toFixed(4), y: +y.toFixed(4) } : item)) }));
    setPlacing(null);
  }

  async function save() {
    setError("");
    setNotice("");
    const located = (item, what) => {
      const where = parseLocation(item.where ?? "");
      if (where === null) throw new Error(`The location of ${what} is not "latitude, longitude" or a Google Maps link.`);
      return where;
    };
    let body;
    try {
      body = {
        buildings: rows.buildings.map((b) => ({ code: b.code.trim().toUpperCase(), name: b.name.trim(), floors: Number(b.floors) || 0,
                                                x: b.x ?? null, y: b.y ?? null, ...located(b, `Building ${b.code || "?"}`) })),
        places: rows.places.map((p) => ({ name: p.name.trim(), words: p.words.split(",").map((w) => w.trim()).filter(Boolean),
                                          x: p.x ?? null, y: p.y ?? null, ...located(p, p.name || "a place") })),
        ...(image !== null ? { image } : {}),
      };
    } catch (err) {
      return setError(err.message);
    }
    if (body.buildings.some((b) => !b.code || !b.name) || body.places.some((p) => !p.name)) {
      return setError("Every building needs a code and a name, and every place a name.");
    }
    setBusy(true);
    try {
      await call((token) => request("/admin/campus", { method: "PUT", token, body }));
      const fresh = await call((token) => request("/admin/campus", { token }));
      setCampus(fresh);
      setRows(toRows(fresh));
      setImage(null);
      setNotice("Campus map saved. Assistants with the campus map skill show it under their answers.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const marker = (list, item, index) => item.x != null && (
    <span key={`${list}-${index}`} className={list === "buildings" ? "cmark" : "cmark place"}
          style={{ left: `${item.x * 100}%`, top: `${item.y * 100}%` }}>
      {list === "buildings" ? item.code || "?" : "📍"}
    </span>
  );
  const placeButton = (list, index, item) => (
    <button type="button" className="opt" aria-pressed={placing?.[0] === list && placing?.[1] === index} disabled={!picture}
            title={picture ? "Then click on the picture" : "Upload a campus picture first"}
            onClick={() => setPlacing(placing?.[0] === list && placing?.[1] === index ? null : [list, index])}>
      {item.x != null ? "✓ On the picture" : "Place on picture"}
    </button>
  );

  return (
    <div className="campus-editor">
      <h4>Campus map</h4>
      <p className="note">
        Shared by every assistant with the campus map skill. Room codes are the building’s code, the floor and a two-digit
        number: <b>B204</b> is Building B, 2nd floor, room 04 (floor 0 is the ground floor). Rooms, buildings and places
        named in an answer are shown on the map.
      </p>

      <div className="field"><span>Picture</span><span className="opts">
        <label className="ghost-button">
          {picture ? "Change picture" : "Upload campus picture"}
          <input type="file" accept="image/png,image/jpeg,image/webp" onChange={pickImage} hidden />
        </label>
        {picture && <button type="button" className="ghost" onClick={() => { setImage(""); setPlacing(null); }}>Remove</button>}
        {!picture && <span className="note">Optional: a plan or an aerial photo. PNG, JPEG or WebP, up to 3 MB.</span>}
      </span></div>
      {picture && (
        <div className={placing ? "cpicture placing" : "cpicture"} onClick={place}>
          <img src={picture} alt="Campus" />
          {rows.buildings.map((b, i) => marker("buildings", b, i))}
          {rows.places.map((p, i) => marker("places", p, i))}
          {placing && <span className="cpicture-hint">Click where {placing[0] === "buildings"
            ? `Building ${rows.buildings[placing[1]].code || "?"}` : rows.places[placing[1]].name || "the place"} is</span>}
        </div>
      )}

      <div className="crows">
        <b>Buildings</b>
        {rows.buildings.map((b, i) => (
          <div className="crow-item" key={i}>
            <input className="finput code" value={b.code} onChange={change("buildings", i, "code")} maxLength={3} placeholder="B" aria-label="Code" />
            <input className="finput" value={b.name} onChange={change("buildings", i, "name")} maxLength={80} placeholder="Engineering Building" aria-label="Name" />
            <label className="cfloors">Floors <input className="finput" type="number" min="0" max="9" value={b.floors}
                                                    onChange={change("buildings", i, "floors")} aria-label="Floors above the ground floor" /></label>
            <input className="finput" value={b.where} onChange={change("buildings", i, "where")} placeholder="Entrance: lat, lng or Maps link" aria-label="Entrance location" />
            {placeButton("buildings", i, b)}
            <button type="button" className="ghost" onClick={() => remove("buildings", i)} aria-label={`Remove building ${b.code}`}>✕</button>
          </div>
        ))}
        <span><button type="button" className="ghost" onClick={() => add("buildings", { code: "", name: "", floors: 2, where: "", x: null, y: null })}>＋ Add building</button></span>
        <span className="note">Floors: how many floors above the ground floor (0 = ground floor only).</span>
      </div>

      <div className="crows">
        <b>Places outside the buildings</b>
        {rows.places.map((p, i) => (
          <div className="crow-item" key={i}>
            <input className="finput" value={p.name} onChange={change("places", i, "name")} maxLength={60} placeholder="Cafeteria" aria-label="Name" />
            <input className="finput" value={p.words} onChange={change("places", i, "words")} placeholder="Other words: food, كافيتريا" aria-label="Other words for it" />
            <input className="finput" value={p.where} onChange={change("places", i, "where")} placeholder="lat, lng or Maps link" aria-label="Location" />
            {placeButton("places", i, p)}
            <button type="button" className="ghost" onClick={() => remove("places", i)} aria-label={`Remove ${p.name}`}>✕</button>
          </div>
        ))}
        <span><button type="button" className="ghost" onClick={() => add("places", { name: "", words: "", where: "", x: null, y: null })}>＋ Add place</button></span>
      </div>

      {notice && <p className="notice">{notice}</p>}
      {error && <p className="error">{error}</p>}
      <div className="crow">
        <span className="note">{dirty ? "Unsaved campus changes" : rows.buildings.length || rows.places.length ? "Saved" : "No buildings yet: the map is off until you add one"}</span>
        <span className="actions">
          {dirty && <button type="button" className="ghost" onClick={() => { setRows(toRows(campus)); setImage(null); setPlacing(null); }} disabled={busy}>Undo</button>}
          <button type="button" onClick={save} disabled={busy || !dirty}>Save campus map</button>
        </span>
      </div>
    </div>
  );
}
