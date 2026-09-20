insert into public.seed_incidents
  (area_name, latitude, longitude, occurred_at, incident_type, description, source_name, source_url, season_tag)
values
  ('Jalan Kaliurang (Sekip/UGM)', -7.7580, 110.4080, '2025-02-20 02:30+07', 'pencurian dengan kekerasan', 'Penyerangan terhadap pengendara sepeda motor pada dini hari di kawasan Kaliurang.', 'Jogja Police Watch via Tirto.id', '', ''),
  ('Ring Road Utara (Mlati)', -7.7490, 110.3600, '2025-03-05 01:15+07', 'pembacokan', 'Korban pengendara motor dibacok kelompok remaja di Ring Road Utara.', 'Jogja Police Watch via Tirto.id', '', ''),
  ('Malioboro & Tugu', -7.7927, 110.3658, '2025-03-12 23:40+07', 'penodongan', 'Penodongan terhadap pejalan kaki di sekitaran Tugu.', 'Data JPW', '', ''),
  ('Gamping & Ambarketawang', -7.7900, 110.3200, '2025-03-18 02:00+07', 'pencurian dengan kekerasan', 'Klitih terhadap pengendara di jalur Gamping saat malam.', 'Data JPW', '', ''),
  ('Depok & Berbah', -7.7600, 110.4300, '2025-03-25 03:10+07', 'kejar-kejaran', 'Kejar-kejaran kelompok remaja mengakibatkan korban jatuh dari motor.', 'Data JPW', '', ''),
  ('Jalan Wonosari (Piyungan)', -7.8400, 110.4600, '2025-04-02 22:50+07', 'pembacokan', 'Penyerangan di jalur Wonosari saat malam.', 'Data JPW', '', ''),
  ('Kotagede', -7.8300, 110.4000, '2025-04-10 01:30+07', 'pencurian dengan kekerasan', 'Klitih terhadap pengendara di kawasan Kotagede.', 'Data JPW', '', ''),
  ('Sleman Kota & Tempel', -7.7100, 110.3300, '2024-03-15 03:00+07', 'pembacokan', 'Lonjakan kasus menjelang Ramadan di jalur utara Sleman.', 'Data JPW (pola Ramadan/SOTR)', '', 'ramadan'),
  ('Wates & Kulon Progo', -7.8600, 110.1600, '2025-04-22 02:20+07', 'pencurian kendaraan', 'Percobaan pencurian motor dengan intimidasi fisik.', 'Data JPW', '', '');

-- Skor kerawanan per area per jam (cold-start; naik tajam 00.00–04.00 & 22.00–23.59)
insert into public.risk_scores (area_name, center, hour_of_day, score, source)
select a.name, point(a.lng, a.lat), h,
  least(100, greatest(5,
    a.base_score + a.night_amp * (case
      when h between 0 and 4 then 1.0
      when h between 22 and 23 then 0.75
      when h between 5 and 6 then 0.45
      else 0.0 end) + ((random() * 8) - 4))),
  'seed'
from (
  values
    ('Malioboro & Tugu', -7.7927, 110.3658, 38, 28),
    ('Jalan Kaliurang (Sekip/UGM)', -7.7580, 110.4080, 34, 34),
    ('Ring Road Utara (Mlati)', -7.7490, 110.3600, 30, 40),
    ('Ring Road Timur (Depok)', -7.7900, 110.4300, 28, 42),
    ('Gamping & Ambarketawang', -7.7900, 110.3200, 26, 44),
    ('Depok & Berbah', -7.7600, 110.4300, 28, 40),
    ('Jalan Wonosari (Piyungan)', -7.8400, 110.4600, 24, 42),
    ('Kotagede', -7.8300, 110.4000, 26, 40),
    ('Sleman Kota & Tempel', -7.7100, 110.3300, 22, 44),
    ('Wates & Kulon Progo', -7.8600, 110.1600, 20, 42),
    ('Bantul Kota', -7.8880, 110.3280, 20, 38),
    ('Kaliurang Utara (Kopeng)', -7.6800, 110.4200, 18, 40)
) as a(name, lat, lng, base_score, night_amp)
cross join generate_series(0, 23) as h;

insert into public.reports (description, location_text, location, occurred_at, incident_type, status)
values
  ('Dua pemuda menodong pengendara motor di dekat Tugu jam setengah dua malam tadi. Korban selamat, motornya dibawa kabur.', 'Malioboro & Tugu', point(110.3658, -7.7927), now() - interval '1 day', 'penodongan', 'terverifikasi'),
  ('Kejar-kejaran kelompok remaja di Ring Road Timur mengakibatkan satu pengendara jatuh. Tolong waspada jam 23.00 sampai 01.00.', 'Ring Road Timur (Depok)', point(110.4300, -7.7900), now() - interval '2 days', 'kejar-kejaran', 'terverifikasi');