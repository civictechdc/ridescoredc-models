-- Martin MVT tile function for the scored road segments.
-- WORK IN PROGRESS: parked in schema/ and NOT applied by yoyo. When it's ready,
-- move it back to functions/ so post-apply.py re-applies it (CREATE OR REPLACE)
-- on every run. Until then the live tile function is `update_score` (v1), which
-- ships inside the schema/0001_baseline.sql pg_dump.
--
-- Contract coupling (keep in sync):
--   * function name  == Martin endpoint  == frontend /tiles/<name>/
--   * ST_AsMVT layer == frontend `source-layer`  ('update_score_v2')
--   * ogc_fid        == frontend promoteId / feature-state key
--
-- user_score is the ONLY value computed per request (a weighted blend of the
-- precomputed *_score columns using the i_* query params). lts_level and the
-- raw attributes are precomputed in the pipeline and passed straight through.

CREATE OR REPLACE FUNCTION public.update_score_v2(z integer, x integer, y integer, query_params json)
RETURNS bytea
LANGUAGE plpgsql STABLE PARALLEL SAFE STRICT
AS $function$
DECLARE mvt bytea; bounds geometry;
BEGIN
  bounds := ST_TileEnvelope(z, x, y);
  SELECT INTO mvt ST_AsMVT(tile, 'update_score_v2', 4096, 'geom')
  FROM (
    SELECT ST_AsMVTGeom(ST_Transform(wkb_geometry, 3857), bounds, 4096, 64, true) AS geom,
      ogc_fid,
      (ridescore_v1*(query_params->>'i_ridescore')::int
        + speedlimit_score*(query_params->>'i_speedlimit')::int
        + num_lanes_score*(query_params->>'i_numlanes')::int
        + facility_score*(query_params->>'i_facility')::int
        + function_score*(query_params->>'i_function')::int
        + road_width_score*(query_params->>'i_roadwidth')::int
        + pavement_condition_score*(query_params->>'i_pavement')::int)
      / ((query_params->>'i_ridescore')::int
        + (query_params->>'i_speedlimit')::int
        + (query_params->>'i_numlanes')::int
        + (query_params->>'i_facility')::int
        + (query_params->>'i_function')::int
        + (query_params->>'i_roadwidth')::int
        + (query_params->>'i_pavement')::int) AS user_score,
      route_name, bike_facility_type, function, lts_level, num_lanes_raw,
      parking_presence, pavement_condition, ridescore_v1, road_width, speed_limit_raw
    FROM ridescoredc WHERE wkb_geometry && ST_Transform(bounds, 4326)
  ) AS tile WHERE geom IS NOT NULL;
  RETURN mvt;
END;
$function$;
