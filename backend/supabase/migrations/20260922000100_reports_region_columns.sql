-- =====================================================================
-- Kolom wilayah di reports (form berjenjang): kabkota_kode, kecamatan_kode, kelurahan_kode,
-- jalan, plus coordinate_source (asal koordinat laporan). Butuh tabel `areas`
-- (20260922000000_create_areas.sql) sudah ada.
--
-- Hierarki dijaga FK ke areas(kode) DAN CHECK prefiks kode. Semua kolom nullable supaya laporan
-- lama dan jalur lama (location_text saja) tetap valid.
--
-- PRIVASI: `jalan` adalah teks bebas pengguna (bisa mengarah ke rumah). Tidak boleh dipublikasikan
-- — hanya backend (service role) dan moderator yang bisa membacanya; endpoint publik tidak
-- boleh memilihnya.
-- =====================================================================

alter table reports
  add column if not exists kabkota_kode text references areas (kode),
  add column if not exists kecamatan_kode text references areas (kode),
  add column if not exists kelurahan_kode text references areas (kode),
  add column if not exists jalan text,
  add column if not exists coordinate_source text;

alter table reports
  add constraint reports_kecamatan_in_kabkota check (
    kecamatan_kode is null
    or (kabkota_kode is not null and kecamatan_kode like kabkota_kode || '.%')
  ),
  add constraint reports_kelurahan_in_kecamatan check (
    kelurahan_kode is null
    or (kecamatan_kode is not null and kelurahan_kode like kecamatan_kode || '.%')
  ),
  add constraint reports_jalan_length check (jalan is null or length(jalan) <= 200),
  add constraint reports_coordinate_source_valid check (
    coordinate_source is null or coordinate_source in ('client', 'kelurahan', 'kecamatan', 'geocoder')
  );

create index if not exists idx_reports_kecamatan_kode on reports (kecamatan_kode);

comment on column reports.jalan is
  'PRIVAT: nama jalan/patokan teks bebas dari pelapor. JANGAN dipublikasikan.';
comment on column reports.coordinate_source is
  'Asal koordinat: client (dikirim pelapor), kelurahan/kecamatan (pusat wilayah), geocoder (Mapbox, diterima setelah validasi). NULL = laporan lama.';
