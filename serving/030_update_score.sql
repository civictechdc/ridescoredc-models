-- The scored road tiles for the map.
--
-- The seven i_* weights are chosen per user, per request, so this has to be a
-- function rather than a view. `user_score` is the only value computed here;
-- every other column is passed straight through from the loaded package.
--
-- Reads two tables, because the pipeline keeps a street's attributes and a
-- model's claims about that street in separate datasets. Joining them is a
-- serving decision, not something the pipeline bakes in.
--
-- Provisional: hand-written, and Proposal 0004 §4.5 says these emissions should
-- be generated ("none of them is hand-written"). It is replaced by
-- `ridescore generate` when that exists.
CREATE OR REPLACE FUNCTION serving.update_score(
    z integer, x integer, y integer, query_params json
)
RETURNS bytea
LANGUAGE plpgsql STABLE PARALLEL SAFE STRICT
AS $function$
DECLARE
    mvt bytea;
    bounds geometry;
    w_ridescore  int := coalesce((query_params->>'i_ridescore')::int, 0);
    w_speedlimit int := coalesce((query_params->>'i_speedlimit')::int, 0);
    w_numlanes   int := coalesce((query_params->>'i_numlanes')::int, 0);
    w_facility   int := coalesce((query_params->>'i_facility')::int, 0);
    w_function   int := coalesce((query_params->>'i_function')::int, 0);
    w_roadwidth  int := coalesce((query_params->>'i_roadwidth')::int, 0);
    w_pavement   int := coalesce((query_params->>'i_pavement')::int, 0);
    w_total      int;
BEGIN
    -- Defect 1 of Proposal 0004 §2: the deployed function has no COALESCE on
    -- the parameters, so one missing weight nulls every score and the map goes
    -- grey with no error. Handled above.
    w_total := w_ridescore + w_speedlimit + w_numlanes + w_facility
             + w_function + w_roadwidth + w_pavement;

    -- Defect 3: the deployed function divides by that total unguarded, so all
    -- weights at zero raises a division-by-zero. NULLIF returns no score
    -- instead, which the frontend can render as "unscored".
    bounds := ST_TileEnvelope(z, x, y);

    SELECT INTO mvt ST_AsMVT(tile, 'update_score', 4096, 'geom')
    FROM (
        SELECT
            ST_AsMVTGeom(ST_Transform(g.geometry, 3857), bounds, 4096, 64, true) AS geom,
            g.tile_id,
            g.segment_id,
            ( s.ridescore_v1              * w_ridescore
            + s.speedlimit_score          * w_speedlimit
            + s.num_lanes_score           * w_numlanes
            + s.facility_score            * w_facility
            + s.function_score            * w_function
            + s.road_width_score          * w_roadwidth
            + s.pavement_condition_score  * w_pavement
            ) / NULLIF(w_total, 0) AS user_score,
            g.route_name,
            g.bike_facility_type,
            g.function,
            g.num_lanes_raw,
            g.parking_presence,
            g.pavement_condition,
            g.road_width,
            g.speed_limit_raw,
            s.lts_level,
            s.ridescore_v1
        FROM data.road_segment g
        JOIN data.ridescore_v1_scores s USING (segment_id)
        WHERE g.geometry && ST_Transform(bounds, 4326)
    ) AS tile
    WHERE geom IS NOT NULL;

    RETURN mvt;
END;
$function$;
