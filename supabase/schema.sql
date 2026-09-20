-- =============================================================
-- GARDU — Skema Database Supabase (PostgreSQL + pgvector)
-- =============================================================

create extension if not exists vector;

create type report_status as enum ('menunggu_verifikasi', 'terverifikasi', 'duplikat', 'hoaks');
create type risk_level as enum ('aman', 'waspada', 'rawan');

-- 3. Laporan warga (ANONIM — REQ-NF-120: tanpa kolom identitas)
create table if not exists public.reports (
  id             uuid primary key default gen_random_uuid(),
  description    text not null check (char_length(description) >= 20),
  location_text  text not null,
  location       point,
  occurred_at    timestamptz not null,
  incident_type  text,
  status         report_status not null default 'menunggu_verifikasi',
  embedding      vector(768),
  cluster_id     uuid,
  ai_summary     text,
  flagged_reason text,
  created_at     timestamptz not null default now()
);

create index if not exists reports_status_idx   on public.reports (status);
create index if not exists reports_occurred_idx on public.reports (occurred_at desc);
create index if not exists reports_embedding_idx on public.reports
  using ivfflat (embedding vector_cosine_ops);

-- 4. Klaster insiden
create table if not exists public.incident_clusters (
  id                    uuid primary key default gen_random_uuid(),
  title                 text,
  primary_location_text text,
  centroid              point,
  report_count          int not null default 1,
  first_seen_at         timestamptz not null default now(),
  last_seen_at          timestamptz not null default now()
);

alter table public.reports
  add constraint reports_cluster_fk
  foreign key (cluster_id) references public.incident_clusters(id) on delete set null;

-- 5. Skor kerawanan per area & jam
create table if not exists public.risk_scores (
  id          bigint generated always as identity primary key,
  area_name   text not null,
  center      point not null,
  hour_of_day int not null check (hour_of_day between 0 and 23),
  score       numeric(5,2) not null check (score between 0 and 100),
  level       risk_level generated always as (
                case when score < 40 then 'aman'::risk_level
                     when score < 70 then 'waspada'::risk_level
                     else 'rawan'::risk_level end
              ) stored,
  source      text not null default 'seed',
  source_url  text,
  computed_at timestamptz not null default now()
);

create index if not exists risk_scores_hour_idx on public.risk_scores (hour_of_day);
create index if not exists risk_scores_area_idx on public.risk_scores (area_name);

-- 6. Seed incidents (REQ-F-024: metadata sumber)
create table if not exists public.seed_incidents (
  id bigint generated always as identity primary key,
  area_name text not null,
  latitude double precision not null,
  longitude double precision not null,
  occurred_at timestamptz not null,
  incident_type text not null,
  description text,
  source_name text,
  source_url text,
  season_tag text
);

-- 7. Riwayat pengecekan rute
create table if not exists public.route_checks (
  id uuid primary key default gen_random_uuid(),
  origin_text text not null,
  destination_text text not null,
  depart_at timestamptz not null,
  result jsonb,
  created_at timestamptz not null default now()
);

-- 8. Row Level Security
alter table public.reports enable row level security;
alter table public.risk_scores enable row level security;
alter table public.seed_incidents enable row level security;
alter table public.incident_clusters enable row level security;
alter table public.route_checks enable row level security;

create policy "risk_scores_public_read" on public.risk_scores
  for select to anon, authenticated using (true);
create policy "seed_incidents_public_read" on public.seed_incidents
  for select to anon, authenticated using (true);
create policy "reports_public_insert" on public.reports
  for insert to anon, authenticated with check (char_length(description) >= 20);
create policy "reports_public_read_verified" on public.reports
  for select to anon, authenticated using (status = 'terverifikasi');
create policy "reports_admin_all" on public.reports
  for all to authenticated using (true) with check (true);
create policy "clusters_admin_read" on public.incident_clusters
  for select to authenticated using (true);
create policy "route_checks_public_insert" on public.route_checks
  for insert to anon, authenticated with check (true);

-- 9. Pencarian laporan mirip (REQ-F-011)
create or replace function match_reports(
  query_embedding vector(768),
  match_threshold float default 0.82,
  match_count int default 5
)
returns setof public.reports language sql stable as $$
  select * from public.reports
  where embedding is not null
    and 1 - (embedding <=> query_embedding) > match_threshold
  order by embedding <=> query_embedding
  limit match_count;
$$;

-- 10. Agregasi risiko sepanjang rute (opsional, via supabase.rpc)
create or replace function risk_along_route(
  origin_lat double precision, origin_lng double precision,
  dest_lat double precision, dest_lng double precision,
  p_hour int, p_samples int default 24
) returns jsonb language plpgsql stable as $$
declare result jsonb;
begin
  with samples as (
    select (origin_lng + (dest_lng - origin_lng) * i / (p_samples - 1.0)) as lng,
           (origin_lat + (dest_lat - origin_lat) * i / (p_samples - 1.0)) as lat
    from generate_series(0, p_samples - 1) as i
  ),
  hits as (
    select distinct rs.area_name, rs.score
    from samples s
    join public.risk_scores rs on rs.hour_of_day = p_hour
    where abs(rs.center[0] - s.lng) < 0.008 and abs(rs.center[1] - s.lat) < 0.008
  )
  select jsonb_build_object(
    'max_score', coalesce((select max(score) from hits), 0),
    'level', case when coalesce((select max(score) from hits), 0) < 40 then 'aman'
                  when coalesce((select max(score) from hits), 0) < 70 then 'waspada'
                  else 'rawan' end,
    'hotspots', coalesce((select jsonb_agg(
        jsonb_build_object('name', area_name, 'score', score) order by score desc)
        from hits where score >= 60), '[]'::jsonb)
  ) into result;
  return result;
end; $$;