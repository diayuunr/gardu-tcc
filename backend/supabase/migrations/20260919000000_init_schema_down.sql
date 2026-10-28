-- =====================================================================
-- Rollback untuk 20260919000000_init_schema.sql
-- Jalankan manual lewat Supabase SQL editor / CLI kalau perlu membatalkan
-- migration awal ini. TIDAK dijalankan otomatis oleh Supabase CLI.
--
-- Urutan DROP mengikuti kebalikan dependency (child sebelum parent) agar
-- tidak melanggar foreign key.
-- =====================================================================

drop policy if exists "public_read_risk_scores" on risk_scores;
drop table if exists risk_scores;

drop policy if exists "moderators_read_own_row" on moderators;
drop policy if exists "moderators_select_incidents" on incidents;
drop policy if exists "moderators_update_reports" on reports;
drop policy if exists "moderators_select_reports" on reports;

drop table if exists moderators;
drop table if exists reports;
drop table if exists incidents;

-- Extension sengaja TIDAK di-drop otomatis — bisa dipakai objek lain di
-- database yang sama. Hapus manual hanya kalau benar-benar yakin tidak
-- ada tabel lain yang bergantung pada tipe `vector`.
-- drop extension if exists vector;
