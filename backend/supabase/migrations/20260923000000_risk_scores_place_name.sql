-- =====================================================================
-- Nama wilayah nyata untuk skor kerawanan (menggantikan label grid "Area -7.795, 110.365" di
-- tampilan publik). Diisi saat perhitungan ulang skor (python -m app.scripts.recalculate_risk):
-- kecamatan TERDEKAT dari pusat sel grid (dari tabel areas), dalam batas jarak wajar.
--
-- Kunci unik (area_name, time_bucket) TIDAK berubah; area_name tetap label grid netral dan
-- place_name hanya label tampilan. Nilai NULL = belum dihitung ulang atau tak ada kecamatan dekat
-- (tampilan jatuh ke label grid). Data publik: nama wilayah agregat, tanpa data individu.
--
-- Butuh tabel `areas` (20260922000000_create_areas.sql). SETELAH migrasi ini jalankan
-- `python -m app.scripts.recalculate_risk` sekali supaya kolom terisi.
-- =====================================================================

alter table risk_scores
  add column if not exists place_name text,
  add column if not exists kecamatan_kode text references areas (kode) on delete set null;

create index if not exists idx_risk_scores_kecamatan_kode on risk_scores (kecamatan_kode);

comment on column risk_scores.place_name is
  'Label publik wilayah, mis. "Kec. Gondokusuman" (kecamatan terdekat dari pusat sel). NULL = pakai area_name.';
comment on column risk_scores.kecamatan_kode is
  'Kode kecamatan terdekat dari pusat sel grid (areas.kode), NULL bila tak ada kecamatan dalam jarak wajar.';
