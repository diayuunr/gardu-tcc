-- Jalankan 20260922000100_reports_region_columns_down.sql LEBIH DULU (kolom reports mengacu ke areas).
drop policy if exists "public_read_areas" on areas;
drop table if exists areas;
