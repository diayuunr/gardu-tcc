-- Rollback untuk 20260920000000_match_similar_reports_fn.sql
drop function if exists match_similar_reports(
  vector(768), uuid, timestamptz, timestamptz, double precision, double precision,
  double precision, double precision, int
);
