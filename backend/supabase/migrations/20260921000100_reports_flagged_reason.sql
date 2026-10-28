-- =====================================================================
-- Kolom alasan penandaan laporan (REQ-F-012). Diisi Verification Agent saat
-- menandai ditandai_duplikat / ditandai_hoaks, supaya moderator tahu KENAPA.
-- Hanya KODE alasan tetap (mis. 'karakter_berulang', 'mirip_laporan_lain'),
-- bukan kutipan teks laporan — tidak menambah data pribadi (REQ-NF-120).
-- =====================================================================

alter table reports
  add column if not exists flagged_reason text;

comment on column reports.flagged_reason is
  'Kode alasan penandaan otomatis (tanpa_huruf, karakter_berulang, kata_berulang, mirip_laporan_lain). NULL = tidak ditandai.';
