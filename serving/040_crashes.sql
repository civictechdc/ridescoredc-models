-- Crash locations for the map.
--
-- A view rather than a published table, for the same reason as the road
-- geometry: what the map shows is a presentation decision, and this schema is
-- where those decisions are written. The crash data itself lives in `data` and
-- is replaced wholesale whenever a new package is loaded.
--
-- The columns named here are the ones the map's popup displays. Adding another
-- is a one-line change; the two the popup does not use --
-- `unknown_injuries_bicyclist` and `bicyclists_impaired` -- are left out so the
-- tiles carry what is drawn and nothing else.
--
-- Martin publishes this as an ordinary table source called `crashes`. It takes
-- no parameters, so its tiles are cacheable.
CREATE OR REPLACE VIEW serving.crashes AS
SELECT
    report_date,
    address,
    major_injuries_bicyclist,
    minor_injuries_bicyclist,
    fatal_bicyclist,
    total_bicycles,
    total_vehicles,
    total_pedestrians,
    geometry
FROM data.crashes;
