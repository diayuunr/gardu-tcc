drop index if exists idx_reports_kecamatan_kode;

alter table reports
  drop constraint if exists reports_coordinate_source_valid,
  drop constraint if exists reports_jalan_length,
  drop constraint if exists reports_kelurahan_in_kecamatan,
  drop constraint if exists reports_kecamatan_in_kabkota;

alter table reports
  drop column if exists coordinate_source,
  drop column if exists jalan,
  drop column if exists kelurahan_kode,
  drop column if exists kecamatan_kode,
  drop column if exists kabkota_kode;
