drop index if exists idx_reports_created_at;
drop index if exists idx_reports_public_number;

alter table reports
  drop constraint if exists reports_incident_type_hint_valid,
  drop constraint if exists reports_moderation_decision_valid;

alter table reports
  drop column if exists moderated_by,
  drop column if exists moderated_at,
  drop column if exists moderation_decision,
  drop column if exists incident_type_hint,
  drop column if exists public_number;
