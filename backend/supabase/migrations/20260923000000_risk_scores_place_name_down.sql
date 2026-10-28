drop index if exists idx_risk_scores_kecamatan_kode;

alter table risk_scores
  drop column if exists kecamatan_kode,
  drop column if exists place_name;
