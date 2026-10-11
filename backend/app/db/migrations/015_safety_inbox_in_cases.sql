-- Milestone 14: cases that arrive through the mock safety API (mock_safety.inbox) are another safety source.
-- Inbox ids are offset by 1,000,000,000 so they never collide with safety.case_versions ids (failures and citations refer to v_cases#id).
CREATE OR REPLACE VIEW safety.v_cases AS
SELECT id, safetyreportid, version, subject_ref, to_date(receivedate, 'YYYYMMDD') AS received, causality, narrative, available_on,
       payload->>'serious' AS serious,
       payload->'patient'->'reaction'->0->>'reactionmeddrapt' AS reaction_term,
       to_date(payload->'patient'->'reaction'->0->>'reactionstartdate', 'YYYYMMDD') AS onset,
       payload->'patient'->'reaction'->0->>'reactionoutcome' AS outcome,
       payload->>'seriousnessdeath' AS death
FROM safety.case_versions
UNION ALL
SELECT 1000000000 + i.id, i.message->'payload'->>'safetyreportid', COALESCE((i.message->>'version')::int, 1), i.message->>'subject_ref',
       to_date(i.message->'payload'->>'receivedate', 'YYYYMMDD'), i.message->>'causality', i.message->>'narrative', (i.message->>'available_on')::date,
       i.message->'payload'->>'serious',
       i.message->'payload'->'patient'->'reaction'->0->>'reactionmeddrapt',
       to_date(i.message->'payload'->'patient'->'reaction'->0->>'reactionstartdate', 'YYYYMMDD'),
       i.message->'payload'->'patient'->'reaction'->0->>'reactionoutcome',
       i.message->'payload'->>'seriousnessdeath'
FROM mock_safety.inbox i WHERE i.status = 'received';
GRANT SELECT, INSERT ON mock_safety.inbox TO data_manager, central_monitor;
GRANT USAGE ON SEQUENCE mock_safety.inbox_id_seq TO data_manager, central_monitor;
