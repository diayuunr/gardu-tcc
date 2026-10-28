-- =====================================================================
-- Data wilayah berjenjang (kabupaten/kota > kecamatan > kelurahan/desa) untuk form
-- laporan (dropdown berjenjang), koordinat awal laporan, dan nama wilayah skor risiko.
--
-- Kode mengikuti Kemendagri DIY: 34.04 / 34.04.02 / 34.04.02.2001. Hierarki dijaga di DB
-- lewat FK parent_kode DAN CHECK prefiks (kode anak diawali kode induk + '.'), jadi baris
-- yatim atau salah induk tidak mungkin masuk. Koordinat = titik pusat wilayah (bukan alamat
-- siapa pun) dan boleh NULL (diisi skrip geocode_areas).
--
-- `area` = label lama untuk skor risiko di backend sebelumnya; disimpan apa adanya, tidak
-- dipakai sebagai syarat apa pun.
-- =====================================================================

create table if not exists areas (
  kode text primary key,
  nama text not null check (length(trim(nama)) > 0),
  tingkat text not null check (tingkat in ('kabkota', 'kecamatan', 'kelurahan')),
  parent_kode text references areas (kode),
  latitude double precision check (latitude between -90 and 90),
  longitude double precision check (longitude between -180 and 180),
  area text,
  created_at timestamptz not null default now(),
  constraint areas_kode_format check (
    (tingkat = 'kabkota' and kode ~ '^[0-9]{2}\.[0-9]{2}$')
    or (tingkat = 'kecamatan' and kode ~ '^[0-9]{2}\.[0-9]{2}\.[0-9]{2}$')
    or (tingkat = 'kelurahan' and kode ~ '^[0-9]{2}\.[0-9]{2}\.[0-9]{2}\.[0-9]{4}$')
  ),
  constraint areas_parent_consistent check (
    (tingkat = 'kabkota' and parent_kode is null)
    or (tingkat <> 'kabkota' and parent_kode is not null and kode like parent_kode || '.%')
  ),
  constraint areas_coordinates_pair check ((latitude is null) = (longitude is null))
);

create index if not exists idx_areas_parent_kode on areas (parent_kode);
create index if not exists idx_areas_tingkat on areas (tingkat);

comment on table areas is
  'Wilayah administratif DIY (kabkota > kecamatan > kelurahan). Data publik statis; koordinat = pusat wilayah.';

alter table areas enable row level security;

-- Baca publik (anon & login), tanpa policy tulis: penulisan hanya lewat service role backend
-- (bypass RLS) dengan skrip app/scripts/load_areas.py.
create policy "public_read_areas" on areas
  for select using (true);
