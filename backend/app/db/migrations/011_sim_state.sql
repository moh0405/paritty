-- Additive to spec §8: simulation state and a golden snapshot so `make reset` restores the seeded EDC quickly.
CREATE TABLE ops.sim_state (key text PRIMARY KEY, value jsonb NOT NULL);
CREATE SCHEMA golden;   -- full copies of edc.* + edc_pending.* taken at the end of seeding
GRANT SELECT, INSERT, UPDATE, DELETE ON ops.sim_state TO data_manager, medical_monitor, central_monitor;
GRANT SELECT ON ops.sim_state TO study_lead;
GRANT SELECT ON ALL TABLES IN SCHEMA ops TO eval_admin;
