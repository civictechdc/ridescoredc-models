-- Road geometry for the survey, carrying NO score of any kind.
--
-- A survey respondent must not see our assessment of a street before giving
-- their own, so the survey is served data that contains no score rather than
-- the same data drawn differently. The guarantee is this column list: a view
-- cannot return a column it does not name, and nothing here computes anything.
--
-- Martin publishes this as an ordinary table source. It takes no parameters,
-- so its tiles are cacheable.
CREATE OR REPLACE VIEW serving.survey_segments AS
SELECT
    tile_id,      -- integer, for MapLibre feature-state (per build, not durable)
    segment_id,   -- text, the durable identity feedback is stored against
    route_name,   -- so a respondent can tell which street they are marking
    geometry
FROM data.road_segment;
