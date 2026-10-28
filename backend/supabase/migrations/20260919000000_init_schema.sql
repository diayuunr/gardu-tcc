-- =====================================================================
-- Gardu — skema awal database (reports, incidents, risk_scores, moderators)
-- Sesuai skill `database-design` dan REQ-NF-120/121 (SRS): laporan warga
-- WAJIB anonim, tidak boleh ada kolom identitas pribadi pelapor.
--
-- Dimensi kolom embedding (vector(768)) memakai model Gemini
-- `gemini-embedding-001` dengan output_dimensionality dipaksa 768 (model
-- ini native-nya 3072 dimensi). Model sebelumnya, text-embedding-004,
-- di-retire Google per 14 Januari 2026. Sesuaikan angka ini kalau tim
-- memilih model embedding lain di kemudian hari.
-- =====================================================================

create extension if not exists vector;
create extension if not exists pgcrypto; -- untuk gen_random_uuid()

-- ---------------------------------------------------------------------
-- incidents: klaster kejadian (gabungan >=1 laporan warga yang merujuk
-- kejadian sama) DAN entri seed data historis (kejadian terdokumentasi
-- dari pemberitaan/JPW). Tidak menyimpan data pribadi apa pun.
-- ---------------------------------------------------------------------
create table if not exists incidents (
  id uuid primary key default gen_random_uuid(),
  location_text text not null,
  latitude double precision,
  longitude double precision,
  incident_time timestamptz not null,
  incident_type text,
  status text not null default 'baru'
    check (status in ('baru', 'terverifikasi')),
  is_seed_data boolean not null default false,
  -- Wajib diisi untuk entri seed data (REQ-F-024 / aturan database-design #4):
  -- nama media/JPW yang menjadi rujukan. Bukan kolom identitas pelapor.
  sumber text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint incidents_seed_data_wajib_sumber
    check (not is_seed_data or sumber is not null)
);

comment on column incidents.sumber is
  'Sumber data (nama media/JPW) untuk entri seed data. Wajib diisi kalau is_seed_data = true.';

-- ---------------------------------------------------------------------
-- reports: laporan warga, ANONIM SEPENUHNYA (REQ-NF-120).
-- JANGAN PERNAH menambah kolom nama/no_hp/email/akun_sosial/ip pelapor
-- di tabel ini.
-- ---------------------------------------------------------------------
create table if not exists reports (
  id uuid primary key default gen_random_uuid(),
  description text not null check (length(trim(description)) > 0),
  location_text text not null check (length(trim(location_text)) > 0),
  latitude double precision,
  longitude double precision,
  occurred_at timestamptz not null,
  -- Hasil ekstraksi Report Verification Agent (REQ-F-010), diisi async.
  extracted_incident_type text,
  -- Representasi vektor makna teks laporan (REQ-F-014), dipakai untuk
  -- pencarian kemiripan/clustering (REQ-F-011). Bukan data identitas —
  -- turunan dari isi laporan, bukan dari siapa pelapornya.
  embedding vector(768),
  status text not null default 'menunggu_verifikasi'
    check (status in (
      'menunggu_verifikasi',
      'terverifikasi',
      'ditandai_duplikat',
      'ditandai_hoaks'
    )),
  incident_id uuid references incidents(id) on delete set null,
  created_at timestamptz not null default now()
);

-- Index kemiripan vektor (cosine similarity) — wajib ada, jangan full scan.
create index if not exists idx_reports_embedding_hnsw
  on reports using hnsw (embedding vector_cosine_ops);

create index if not exists idx_reports_incident_id on reports (incident_id);
create index if not exists idx_reports_status on reports (status);

alter table reports enable row level security;
alter table incidents enable row level security;

-- ---------------------------------------------------------------------
-- moderators: pemetaan anggota tim (Supabase Auth user) ke akses panel
-- moderasi (REQ-NF-123). Ini BUKAN identitas pelapor — pelapor tetap
-- anonim; moderators.user_id adalah akun internal tim, bukan warga
-- yang melapor.
-- ---------------------------------------------------------------------
create table if not exists moderators (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references auth.users (id) on delete cascade,
  display_name text not null,
  created_at timestamptz not null default now()
);

alter table moderators enable row level security;

-- Reports/incidents hanya bisa dibaca & diubah oleh moderator yang
-- terautentikasi lewat Supabase Auth (REQ-NF-123). Backend FastAPI
-- memakai service role key sehingga otomatis bypass RLS ini — policy
-- di bawah khusus untuk sesi Supabase Auth langsung dari Panel Moderasi.
create policy "moderators_select_reports" on reports
  for select using (
    exists (select 1 from moderators m where m.user_id = auth.uid())
  );

create policy "moderators_update_reports" on reports
  for update using (
    exists (select 1 from moderators m where m.user_id = auth.uid())
  ) with check (
    exists (select 1 from moderators m where m.user_id = auth.uid())
  );

create policy "moderators_select_incidents" on incidents
  for select using (
    exists (select 1 from moderators m where m.user_id = auth.uid())
  );

create policy "moderators_read_own_row" on moderators
  for select using (auth.uid() = user_id);

-- ---------------------------------------------------------------------
-- risk_scores: skor kerawanan per area/rentang waktu (REQ-F-020..024),
-- dibaca publik oleh Dasbor Peta Kerawanan (REQ-F-040/041) tanpa login.
-- Tidak ada data personal di tabel ini.
-- ---------------------------------------------------------------------
create table if not exists risk_scores (
  id uuid primary key default gen_random_uuid(),
  area_name text not null,
  latitude double precision not null,
  longitude double precision not null,
  -- Bucket waktu, mis. 'dini_hari' (00-04), 'pagi', 'siang', 'sore', 'malam'.
  time_bucket text not null,
  risk_score numeric(4, 2) not null check (risk_score >= 0 and risk_score <= 10),
  risk_level text not null check (risk_level in ('rendah', 'sedang', 'tinggi')),
  contributing_incident_count integer not null default 0,
  last_calculated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint risk_scores_area_time_unique unique (area_name, time_bucket)
);

create index if not exists idx_risk_scores_area_time
  on risk_scores (area_name, time_bucket);

alter table risk_scores enable row level security;

-- Publik boleh membaca skor kerawanan (dasbor & Safe Route Advisor tanpa
-- login), tapi tidak boleh menulis — penulisan hanya lewat backend
-- (service role, bypass RLS) setelah Risk Prediction Agent menghitung ulang.
create policy "public_read_risk_scores" on risk_scores
  for select using (true);
