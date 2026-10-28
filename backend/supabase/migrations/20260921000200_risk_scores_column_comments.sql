-- =====================================================================
-- Dokumentasi kolom risk_scores (hanya COMMENT, tidak mengubah struktur/data):
--   * risk_score disimpan sebagai skor DASAR — pengali musim Ramadan kini
--     diterapkan SAAT DIBACA (risk_agent.apply_seasonality), bukan tertanam.
--   * rentang bucket waktu disamakan dengan kode (TIME_BUCKET_HOURS):
--     dini_hari 00-05 (komentar lama di migrasi awal menulis 00-04).
--
-- SETELAH migrasi ini, jalankan sekali `python -m app.scripts.recalculate_risk`
-- supaya baris lama (yang masih memuat pengali musim lama) diganti skor dasar.
-- =====================================================================

comment on column risk_scores.risk_score is
  'Skor DASAR 0-10 tanpa pengali musim. Pengali Ramadan diterapkan saat dibaca (backend), dibatasi 10.';

comment on column risk_scores.risk_level is
  'Level dari skor DASAR (rendah/sedang/tinggi). Level yang ditampilkan ke pengguna dihitung ulang dari skor akhir setelah pengali musim.';

comment on column risk_scores.time_bucket is
  'Bucket jam WIB: dini_hari 00-05, pagi 05-11, siang 11-15, sore 15-18, malam 18-24 (jam selesai eksklusif).';

comment on column risk_scores.contributing_incident_count is
  'Jumlah insiden di sel ini sendiri. 0 = skor berasal murni dari pengaruh sel tetangga.';
