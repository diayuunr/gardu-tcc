-- =====================================================================
-- Perbaikan match_similar_reports (REQ-F-011/012/013): laporan yang sudah
-- ditandai duplikat/hoaks TIDAK boleh menjadi kecocokan klaster. Sebelumnya
-- laporan duplikat bisa "menarik" laporan baru ke insiden lamanya, atau
-- laporan hoaks yang mirip ikut membentuk klaster dan mengubah skor risiko.
--
-- Signature & tipe kembalian SAMA dengan versi sebelumnya (hanya filter
-- status ditambahkan), jadi `create or replace` cukup dan kode Python lama
-- tetap kompatibel. Kode Python (verify_agent._drop_flagged_matches) juga
-- memfilter ulang sebagai pertahanan kedua.
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
    and r.status not in ('ditandai_duplikat', 'ditandai_hoaks')
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
  'Cari laporan lain yang embedding-nya mirip (cosine similarity), dibatasi rentang waktu & lokasi berdekatan. Laporan berstatus ditandai_duplikat/ditandai_hoaks diabaikan. Dipakai Report Verification & Clustering Agent (REQ-F-011).';
