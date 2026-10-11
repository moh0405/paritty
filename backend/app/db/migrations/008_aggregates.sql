CREATE MATERIALIZED VIEW ops.query_aging_daily WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', ts) AS day, site_id,
  count(*) FILTER (WHERE event='opened') AS opened, count(*) FILTER (WHERE event='closed') AS closed,
  count(*) FILTER (WHERE event='reopened') AS reopened
FROM ops.query_events GROUP BY day, site_id WITH NO DATA;
CREATE MATERIALIZED VIEW edc.site_vitals_weekly WITH (timescaledb.continuous) AS
SELECT site_id, test_code, time_bucket('7 days', measured_at) AS bucket, count(*) AS n,
  avg(value) AS mean, stddev_samp(value) AS sd,
  count(*) FILTER (WHERE value::int % 10 = 0) AS ends0, count(*) FILTER (WHERE value::int % 5 = 0) AS ends05
FROM edc.vitals GROUP BY site_id, test_code, bucket WITH NO DATA;
