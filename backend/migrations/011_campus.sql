-- 011: a campus map for every university, edited in the admin where an assistant has the
-- "Campus map" skill. GIU keeps its built-in map (tenants.campus_map = true, app/campus.py).
--
-- * tenants.campus: the university's buildings and outdoor places (JSON, small):
--   {"buildings": [{"code": "B", "name": "Engineering Building", "floors": 3,
--                   "x": 0.42, "y": 0.31, "lat": 30.01, "lng": 31.70}, ...],
--    "places": [{"key": "cafeteria", "name": "Cafeteria", "words": ["food"], "x", "y", "lat", "lng"}, ...],
--    "image_version": 1731700000}
--   x and y: where it is on the campus picture (0 to 1, from the top left); lat and lng: its
--   entrance, for the "Walk me there" link. Both optional.
-- * tenants.campus_image: the campus picture as a data URL (big, so read only by GET /campus/image).
--
-- giu_app may change both on its own university's row only (the tenants_update_own policy, 007).
-- Safe to run again.

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS campus JSONB;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS campus_image TEXT;
GRANT UPDATE (campus, campus_image) ON tenants TO giu_app;
