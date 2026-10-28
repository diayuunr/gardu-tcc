-- =====================================================================
-- Fungsi pencarian kemiripan vektor untuk Report Verification & Clustering
-- Agent (REQ-F-011). PostgREST/supabase-py tidak expose operator pgvector
-- (`<=>`) lewat query builder biasa, jadi pencarian kemiripan HARUS lewat
-- RPC function seperti ini, dipanggil dari app/agents/verify_agent.py.
--
-- Pembatasan "rentang waktu & lokasi berdekatan" (sesuai IPO REQ Bagian
-- 5.2) diterapkan SEBELUM validasi similarity: filter waktu (time_window)
-- wajib, filter lokasi (bounding box lat/lon) opsional — dilewati kalau
-- salah satu titik (laporan baru atau laporan pembanding) tidak punya
-- koordinat, supaya laporan tanpa geocoding tetap bisa diklasterkan
-- berdasarkan teks & waktu saja.
-- =====================================================================

create or replace function match_similar_reports(
  query_embedding vector(768),
  exclude_report_id uuid,
  time_window_start timestamptz,
  time_window_end timestamptz,
  query_latitude double precision,
  query_longitude double precision,
  max_distance_degrees double precision,
  similarity_threshold double precision,
  match_limit int
)
returns table (
  id uuid,
  incident_id uuid,
  similarity double precision
)
language sql
stable
as $$
  select
    r.id,
    r.incident_id,
    1 - (r.embedding <=> query_embedding) as similarity
  from reports r
  where r.id <> exclude_report_id
    and r.embedding is not null
    and r.occurred_at between time_window_start and time_window_end
    and (
      query_latitude is null or query_longitude is null
      or r.latitude is null or r.longitude is null
      or (
        abs(r.latitude - query_latitude) <= max_distance_degrees
        and abs(r.longitude - query_longitude) <= max_distance_degrees
      )
    )
    and 1 - (r.embedding <=> query_embedding) >= similarity_threshold
  order by r.embedding <=> query_embedding
  limit match_limit;
$$;

comment on function match_similar_reports is
  'Cari laporan lain yang embedding-nya mirip (cosine similarity), dibatasi rentang waktu & lokasi berdekatan. Dipakai Report Verification & Clustering Agent (REQ-F-011).';
