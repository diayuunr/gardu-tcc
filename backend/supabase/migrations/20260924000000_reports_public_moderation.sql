-- =====================================================================
-- Fase E: daftar laporan publik, panel moderasi, dan petunjuk jenis kejadian dari form.
--
--  * public_number   : nomor urut laporan (identity). Dipakai sebagai id PENDEK di endpoint publik
--                      (mis. "GRD-000123") supaya UUID laporan tidak perlu dibagikan.
--  * incident_type_hint : kategori jenis kejadian yang dipilih pelapor dari dropdown (nilai tetap).
--                      Disimpan TERPISAH dari `description` supaya tidak mencemari embedding; dipakai
--                      sebagai petunjuk bila ekstraksi Gemini gagal.
--  * moderation_decision / moderated_at / moderated_by : jejak keputusan moderator (REQ-NF-123).
--                      `moderation_decision = 'disetujui'` membuat insiden tetap terverifikasi walau
--                      hanya satu laporan; NULL = belum pernah diputuskan manusia.
--
-- Semua kolom nullable/berdefault supaya laporan lama tetap valid. Tidak ada kolom identitas pelapor
-- (REQ-NF-120): `moderated_by` merujuk akun INTERNAL tim, bukan warga.
-- =====================================================================

alter table reports
  add column if not exists public_number bigint generated always as identity,
  add column if not exists incident_type_hint text,
  add column if not exists moderation_decision text,
  add column if not exists moderated_at timestamptz,
  add column if not exists moderated_by uuid references moderators (id) on delete set null;

alter table reports
  add constraint reports_moderation_decision_valid check (
    moderation_decision is null or moderation_decision in ('disetujui', 'ditolak')
  ),
  add constraint reports_incident_type_hint_valid check (
    incident_type_hint is null or incident_type_hint in (
      'klitih', 'penyerangan', 'bentrok antar kelompok', 'begal/penodongan',
      'kejadian mencurigakan', 'pengrusakan', 'lainnya'
    )
  );

create unique index if not exists idx_reports_public_number on reports (public_number);
create index if not exists idx_reports_created_at on reports (created_at desc);

comment on column reports.public_number is
  'Nomor urut publik (id pendek "GRD-000123"). Aman dipublikasikan; BUKAN identitas pelapor.';
comment on column reports.incident_type_hint is
  'Kategori jenis kejadian pilihan pelapor (dropdown). Terpisah dari description agar tidak mencemari embedding.';
comment on column reports.moderation_decision is
  'Keputusan moderator terakhir: disetujui | ditolak; NULL = belum diputuskan manusia.';
