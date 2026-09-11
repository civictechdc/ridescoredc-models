-- The serving schema: views and functions the tile server publishes.
-- Proposal 0005 §4.1. Rebuilt on every load, because a full-replace of `data`
-- drops the tables these objects read.
CREATE SCHEMA IF NOT EXISTS serving;
