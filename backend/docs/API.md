# Gardu API — kontrak untuk frontend

Basis URL: nilai `NEXT_PUBLIC_BACKEND_URL` (lokal: `http://localhost:8000`). Dokumentasi interaktif: `GET /docs` (Swagger).
Semua respons JSON. Dokumen ini dilengkapi bertahap per fase; bagian `/risk/score` dan `/risk/heatmap` baru
mencatat field nama wilayah (Fase C), selebihnya lihat `/docs` (Swagger).

## Format error (berlaku untuk semua endpoint)

Semua pesan berbahasa Indonesia, aman ditampilkan langsung ke pengguna, dan tidak pernah memuat detail internal
(host, kunci, traceback) maupun nilai yang dikirim pengguna.

| Status | Bentuk | Kapan |
|---|---|---|
| 422 validasi | `{"detail": "Input tidak valid — Deskripsi: minimal 10 karakter; ...", "errors": [{"field": "description", "message": "minimal 10 karakter"}]}` | Input salah. `detail` = ringkasan siap tampil; `errors` = per-field (maks 5). |
| 422 bisnis | `{"detail": "Kecamatan yang dipilih bukan bagian dari kabupaten/kota tersebut."}` | Hierarki wilayah tidak cocok, dll. |
| 404 / 405 | `{"detail": "Alamat yang diminta tidak ditemukan."}` | Alamat/metode salah. |
| 429 | `{"detail": "Terlalu banyak laporan dikirim dari sumber ini, coba lagi nanti."}` | Rate limit per IP. |
| 502 / 503 | `{"detail": "..."}` | Database/layanan eksternal bermasalah; pesan generik. |
| 500 | `{"detail": "Terjadi kesalahan pada server, silakan coba lagi."}` | Kesalahan tak terduga. |

`detail` selalu berupa **string**.

## Data yang tidak pernah keluar dari API

Kolom `incidents.sumber` (URL/judul berita rujukan data seed, bisa memuat ciri kejadian pada slug-nya) **tidak pernah**
dikembalikan oleh endpoint mana pun, publik maupun moderasi; begitu pula teks lokasi insiden dan koordinat insiden individual.
Dijaga test (`tests/test_sumber_privacy.py`): skema OpenAPI tidak boleh punya field sumber, kode API tidak boleh meminta
kolom itu dari database, dan respons `/route/check`, `/reports/*`, serta `/moderation/*` diperiksa isinya. (Field `source`
pada `/geo/search` adalah asal hasil pencarian tempat — landmark/photon/…, bukan sumber berita.)

---

## `GET /health`

Cek server hidup dan database terjangkau.

- `200` → `{"status": "ok", "database": "ok"}`
- `503` → `{"status": "degraded", "database": "unavailable"}`

---

## `GET /areas`

Wilayah DIY untuk dropdown berjenjang. Publik, tanpa login, di-cache server (TTL `AREAS_CACHE_TTL_SECONDS`, default 600 dtk)
dan `Cache-Control: public, max-age=300`. Hanya data wilayah — tanpa data laporan.

Query (semua opsional):

| Param | Nilai | Keterangan |
|---|---|---|
| `tingkat` | `kabkota` \| `kecamatan` \| `kelurahan` | Filter tingkat. |
| `parent` | kode induk, mis. `34.04` | Hanya anak langsung dari induk itu. |

Respons `200`:

```json
{
  "count": 2,
  "areas": [
    {"kode": "34.04.06", "nama": "Depok", "tingkat": "kecamatan", "parent_kode": "34.04",
     "latitude": -7.77, "longitude": 110.39},
    {"kode": "34.04.05", "nama": "Gamping", "tingkat": "kecamatan", "parent_kode": "34.04",
     "latitude": null, "longitude": null}
  ]
}
```

Terurut nama. `latitude`/`longitude` = titik pusat wilayah (bukan alamat siapa pun), `null` bila belum tersedia atau
tidak valid. Alur dropdown: `GET /areas?tingkat=kabkota` → `GET /areas?tingkat=kecamatan&parent=34.04` →
`GET /areas?tingkat=kelurahan&parent=34.04.06`. Format kode: `34.04` / `34.04.06` / `34.04.06.2001` (Kemendagri DIY).

Error: `422` bila `tingkat`/`parent` tidak valid, `503` bila data wilayah belum bisa dimuat.

---

## `POST /reports`

Kirim laporan anonim. **Tidak ada field identitas pelapor.** Rate limit per IP (`RATE_LIMIT_MAX_REQUESTS` per
`RATE_LIMIT_WINDOW_SECONDS`).

### Request

| Field | Tipe | Wajib | Keterangan |
|---|---|---|---|
| `description` | string, 10–2000 | ya | Deskripsi kejadian. |
| `occurred_at` | ISO 8601 | ya | Waktu kejadian. **Tanpa zona waktu = WIB.** Tidak boleh di masa depan (>5 menit). |
| `kabkota_kode` | string | jalur berjenjang | mis. `34.04`. |
| `kecamatan_kode` | string | jalur berjenjang | mis. `34.04.06`. Wajib bila `kabkota_kode` diisi. |
| `kelurahan_kode` | string | tidak | mis. `34.04.06.2001`. |
| `jalan` | string, maks 200 | tidak | Nama jalan/patokan. Dibersihkan server; email/nomor telepon ditolak. **Privat, tidak pernah dipublikasikan.** |
| `location_text` | string, 3–200 | jalur lama | Hanya dipakai bila **tidak** ada kode wilayah. Bila kode ada, teks ini **diabaikan**. |
| `latitude`, `longitude` | number | tidak | Titik dari peta. Di luar DIY diabaikan (bukan ditolak). |
| `incident_type_hint` | string | tidak | Kategori jenis kejadian dari dropdown: `klitih`, `penyerangan`, `bentrok antar kelompok`, `begal/penodongan`, `kejadian mencurigakan`, `pengrusakan`, `lainnya` (nilai lain → `422`). Disimpan **terpisah** dari `description` (tidak ikut embedding/Gemini) dan hanya dipakai sebagai petunjuk bila ekstraksi Gemini gagal. |

Aturan lokasi — pilih **satu** jalur:

1. **Berjenjang (disarankan):** `kabkota_kode` + `kecamatan_kode` [+ `kelurahan_kode`] [+ `jalan`]. Server memvalidasi
   hierarki ke tabel `areas` dan **menyusun `location_text` sendiri** dari nama wilayah, mis.
   `Jalan Kaliurang km 5, Desa Caturtunggal, Kecamatan Depok, Kabupaten Sleman`.
2. **Lama (kompatibel mundur):** hanya `location_text`. Tanpa `jalan`.

Contoh (berjenjang):

```json
{
  "description": "Ada sekelompok remaja membawa senjata tajam di simpang jalan.",
  "occurred_at": "2026-10-28T22:30:00",
  "kabkota_kode": "34.04",
  "kecamatan_kode": "34.04.06",
  "kelurahan_kode": "34.04.06.2001",
  "jalan": "Jalan Kaliurang km 5"
}
```

### Penyamaran data pribadi (masking)

Laporan **tidak pernah ditolak** karena berisi data pribadi. Sebelum disimpan dan sebelum diproses AI, server menyamarkan
di `description` (dan `location_text` jalur lama): email → `[email disamarkan]`, nomor telepon (`+62…`, `62…`, `08…`,
termasuk telepon rumah `(0274) 512345`) dan NIK 16 digit → `[nomor disamarkan]`. **Nomor polisi kendaraan (`AB 1234 CD`),
jam, tanggal, dan nominal uang tidak disamarkan.** Field `jalan` berbeda: bila berisi email/nomor telepon, request ditolak
`422` agar pelapor mengoreksinya. Sarankan pengguna di formulir untuk tidak menulis data pribadi.

### Contoh untuk frontend (jalur berjenjang)

Alur dropdown berjenjang memakai `GET /areas`, lalu kirim **kode** wilayah (bukan nama) ke `POST /reports`:

```ts
const API = process.env.NEXT_PUBLIC_BACKEND_URL!;

type Area = { kode: string; nama: string; tingkat: "kabkota" | "kecamatan" | "kelurahan"; parent_kode: string | null };

async function loadAreas(tingkat: Area["tingkat"], parent?: string): Promise<Area[]> {
  const query = new URLSearchParams({ tingkat, ...(parent ? { parent } : {}) });
  const response = await fetch(`${API}/areas?${query}`);
  if (!response.ok) throw new Error((await response.json()).detail);
  return (await response.json()).areas;
}

// 1) kabupaten/kota -> 2) kecamatan (parent = kabkota) -> 3) kelurahan (parent = kecamatan, opsional)
const kabkota = await loadAreas("kabkota");
const kecamatan = await loadAreas("kecamatan", "34.04");
const kelurahan = await loadAreas("kelurahan", "34.04.06");

async function submitReport(form: {
  description: string;
  occurredAtLocal: string; // nilai <input type="datetime-local">, mis. "2026-10-28T22:30"
  kabkotaKode: string;
  kecamatanKode: string;
  kelurahanKode?: string;
  jalan?: string;
}) {
  const response = await fetch(`${API}/reports`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      description: form.description,
      occurred_at: form.occurredAtLocal, // tanpa zona waktu = WIB; atau kirim ISO dengan zona (new Date(...).toISOString())
      kabkota_kode: form.kabkotaKode,
      kecamatan_kode: form.kecamatanKode,
      ...(form.kelurahanKode ? { kelurahan_kode: form.kelurahanKode } : {}),
      ...(form.jalan ? { jalan: form.jalan } : {}),
      // Jangan kirim location_text pada jalur ini: server menyusunnya sendiri dari nama wilayah.
    }),
  });
  if (!response.ok) {
    // `detail` selalu string berbahasa Indonesia, siap ditampilkan ke pengguna.
    throw new Error((await response.json()).detail);
  }
  return response.json(); // { id, status: "menunggu_verifikasi", created_at }
}
```

Catatan: kolom `kelurahan_kode` hanya boleh diisi bila `kecamatan_kode` yang sama juga dikirim. Kirim `jalan` hanya bila
diisi (kosong/spasi akan diabaikan server).

### Respons `201`

```json
{"id": "…uuid…", "status": "menunggu_verifikasi", "created_at": "2026-10-28T15:31:00+00:00"}
```

Verifikasi AI berjalan otomatis di latar belakang setelah respons; frontend **tidak** perlu memanggil apa pun lagi.

### Koordinat laporan

Ditentukan seketika (tanpa panggilan jaringan, submit tetap cepat): (1) titik dari klien bila di dalam DIY, (2) pusat
kelurahan, (3) pusat kecamatan. Bila `jalan` diisi (atau jalur lama tanpa titik), server mencoba menyempurnakan
koordinat lewat Mapbox di latar belakang; hasil hanya dipakai bila di dalam DIY dan ≤ `REPORT_GEOCODE_MAX_DISTANCE_METERS`
(default 8000 m) dari pusat wilayah terpilih. Koordinat tidak ada di respons.

### Error khusus

| Status | `detail` (contoh) |
|---|---|
| 422 | `Input tidak valid — Isi lokasi kejadian: pilih kabupaten/kota dan kecamatan, atau tulis lokasinya.` |
| 422 | `Kecamatan yang dipilih bukan bagian dari kabupaten/kota tersebut.` |
| 422 | `Kelurahan/desa yang dipilih bukan bagian dari kecamatan tersebut.` |
| 422 | `Kabupaten/kota tidak ditemukan.` |
| 503 | `Data wilayah sementara tidak dapat diambil, silakan coba lagi.` (hanya jalur berjenjang) |
| 502 | `Laporan gagal disimpan, silakan coba lagi.` |

---

## Laporan publik: `GET /reports/public` dan `GET /reports/stats`

Untuk landing/halaman "laporan terbaru". Publik, tanpa login, **anonim**, di-cache server `PUBLIC_REPORTS_CACHE_SECONDS`
(60 dtk) + `Cache-Control: public, max-age=60`. Batas per-IP `PUBLIC_REPORTS_RATE_LIMIT_MAX_REQUESTS` per
`PUBLIC_REPORTS_RATE_LIMIT_WINDOW_SECONDS` (60/60 dtk → `429`).

### `GET /reports/public?limit=20&offset=0`

`limit` 1–50 (bawaan 20), `offset` ≥ 0. Terbaru dulu. Hanya laporan **menunggu verifikasi** dan **terverifikasi**; yang
ditandai duplikat/hoaks tidak ditampilkan (tetap dihitung di `/reports/stats`).

```json
{
  "total": 2, "limit": 20, "offset": 0,
  "items": [
    {"nomor": "GRD-001042", "status": "terverifikasi", "occurred_at": "2026-10-20T22:00:00+07:00",
     "wilayah": "Kec. Depok, Kabupaten Sleman", "jenis": "penyerangan"}
  ]
}
```

| Field | Keterangan |
|---|---|
| `nomor` | Nomor urut publik (`GRD-` + 6 digit), pengganti UUID. |
| `status` | `menunggu_verifikasi` \| `terverifikasi`. |
| `occurred_at` | Waktu kejadian **dibulatkan ke bawah per jam** (WIB), agar tidak menjadi sidik jari pelapor. |
| `wilayah` | Kecamatan + kabupaten/kota (dari kode wilayah laporan; laporan lama: kecamatan terdekat). `Daerah Istimewa Yogyakarta` bila tak diketahui. |
| `jenis` | Salah satu kategori tetap: `klitih`, `penyerangan`, `bentrok antar kelompok`, `begal/penodongan`, `kejadian mencurigakan`, `pengrusakan`, `lainnya`. Teks bebas (mis. rincian korban) tidak pernah keluar. |

**Tidak pernah ada:** deskripsi, jalan/patokan, koordinat, teks lokasi lengkap, UUID laporan/insiden. Kolom itu bahkan tidak
diminta dari database (diuji).

### `GET /reports/stats`

```json
{
  "total_reports": 128,
  "reports_by_status": {"menunggu_verifikasi": 31, "terverifikasi": 82, "ditandai_duplikat": 9, "ditandai_hoaks": 6},
  "verified_incidents": 21,
  "verified_incidents_from_reports": 21,
  "historical_incidents": 19
}
```

`verified_incidents` = insiden berstatus terverifikasi; `verified_incidents_from_reports` = yang bukan data seed (hasil laporan
warga); `historical_incidents` = data seed historis dari pemberitaan (berstatus `baru` tetapi tetap ikut skor kerawanan).
Hanya angka agregat.

Error untuk keduanya: `429`, `502` (`Data laporan sementara tidak dapat diambil.`).

---

## Panel moderasi: `/moderation/*`

Khusus tim moderator (REQ-F-060/061, REQ-NF-123). **Semua** endpoint wajib header
`Authorization: Bearer <access_token Supabase Auth>` — token dari `supabase.auth.signInWithPassword(...)` /
`getSession()` di frontend (anon key; service role key **tidak pernah** ke frontend). Server memverifikasi token ke
Supabase Auth (bukan sekadar membaca isinya) lalu memastikan pengguna ada di tabel `moderators`.

| Status | Arti |
|---|---|
| `401` | Token hilang/tidak valid/kedaluwarsa (header `WWW-Authenticate: Bearer`) → arahkan ke halaman masuk. |
| `403` | Akun valid tetapi bukan moderator. |
| `429` | Rate limit per-IP (`MODERATION_RATE_LIMIT_MAX_REQUESTS` per `MODERATION_RATE_LIMIT_WINDOW_SECONDS`, 120/60 dtk), dihitung sebelum token diperiksa. |
| `503` | Supabase Auth/DB tidak terjangkau. |

Menambah moderator: buat pengguna di Supabase Auth (Dashboard → Authentication), lalu
`insert into moderators (user_id, display_name) values ('<auth.users.id>', 'Nama Tampil');` di SQL Editor.

### `GET /moderation/me`

`{"display_name": "Mod Satu"}` — untuk gerbang halaman panel (cek token + hak akses).

### `GET /moderation/reports?status=&limit=20&offset=0`

Antrean laporan, terbaru dulu. `status` boleh diulang (`menunggu_verifikasi`, `terverifikasi`, `ditandai_duplikat`,
`ditandai_hoaks`); bawaan: yang butuh tinjauan (menunggu + ditandai duplikat/hoaks). `limit` maks 100.

```json
{
  "total": 1, "limit": 20, "offset": 0,
  "items": [{
    "id": "0b7f…", "nomor": "GRD-001042", "status": "ditandai_hoaks", "flagged_reason": "karakter_berulang",
    "moderation_decision": null, "description": "…", "location_text": "Kec. Depok, Kabupaten Sleman",
    "occurred_at": "2026-10-20T22:00:00+07:00", "created_at": "2026-10-21T03:12:00+00:00",
    "extracted_incident_type": "penyerangan", "incident_type_hint": "klitih", "incident_id": null
  }]
}
```

`flagged_reason` = kode alasan penandaan otomatis: `tanpa_huruf`, `karakter_berulang`, `kata_berulang`,
`mirip_laporan_lain`, atau `ditolak_moderator`. Koordinat tidak disertakan.

### `PATCH /moderation/reports/{id}`

Body `{"status": "terverifikasi" | "ditandai_hoaks" | "menunggu_verifikasi"}` (status lain → `422`).

| `status` | Arti | Efek |
|---|---|---|
| `terverifikasi` | Setujui | Laporan terverifikasi (`moderation_decision=disetujui`). Insidennya menjadi **terverifikasi walau hanya satu laporan**; bila laporan belum punya insiden (mis. tadinya ditandai hoaks), insiden dibuat darinya. |
| `ditandai_hoaks` | Tolak | `moderation_decision=ditolak`, `flagged_reason=ditolak_moderator`; laporan **dicabut dari insidennya**. |
| `menunggu_verifikasi` | Kembalikan ke antrean | Keputusan dan penandaan dihapus; laporan dicabut dari insiden lalu diklasterkan ulang oleh job `/internal/reprocess`. |

Sesudah keputusan, insiden yang terdampak disinkronkan: **terverifikasi** bila ≥ 2 laporan independen atau ada yang
disetujui moderator; kalau tidak turun ke `baru` (laporan yang tadinya terverifikasi otomatis kembali
`menunggu_verifikasi`); tanpa laporan tersisa, insiden hasil laporan dihapus. **Insiden seed tidak pernah diubah.** Bila
status terverifikasi sebuah insiden berubah, skor kerawanan dihitung ulang di latar belakang.

```json
{"id": "0b7f…", "status": "ditandai_hoaks", "changed": true, "incident_status": null, "scores_refresh_scheduled": true}
```

`changed=false` bila laporan sudah berada pada keputusan itu (idempoten — aman diulang). `incident_status` = status insiden
yang masih terhubung dengan laporan (`baru` | `terverifikasi`), `null` bila laporan tidak (lagi) terhubung. Error: `404`
(laporan tidak ada), `422` (id bukan UUID / status tidak diizinkan), `502`.

Catatan: rangkaian pembaruan tidak satu transaksi (Supabase REST). Setiap langkah idempoten; bila server mati di
tengah keputusan, ulangi keputusan yang sama. Laporan berstatus *duplikat* yang disetujui menjadi insiden sendiri —
gunakan hanya bila memang kejadian terpisah.

---

## Endpoint internal: `/internal/*` (penjadwal, bukan untuk browser)

Dilindungi header `X-Internal-Token: <INTERNAL_API_TOKEN>` (string acak ≥ 32 karakter, hanya di environment backend dan
penjadwal). `INTERNAL_API_TOKEN` kosong = endpoint **mati** (`404`). Token salah/hilang → `401`; rate limit per-IP
(`INTERNAL_RATE_LIMIT_MAX_REQUESTS` per `INTERNAL_RATE_LIMIT_WINDOW_SECONDS`, 30/60 dtk). Semuanya `POST`; pekerjaan berjalan
di latar belakang dan respons `202` segera.

### `POST /internal/reprocess?limit=&dry_run=false`

Memproses ulang laporan `menunggu_verifikasi` yang belum tuntas (tanpa embedding / jenis kejadian / insiden, dan lebih tua
dari `REPROCESS_MIN_AGE_MINUTES`) — setara `python -m app.scripts.reprocess_reports`. `limit` dibatasi
`INTERNAL_REPROCESS_MAX_BATCH` (20); jeda antar laporan `REPROCESS_DELAY_SECONDS` (kuota Gemini). `409` bila proses ulang
sebelumnya masih berjalan. Idempoten.

```json
{"found": 3, "queued": 3, "dry_run": false}
```

### `POST /internal/recalculate-risk`

Menghitung ulang skor dasar kerawanan di latar belakang (setara `python -m app.scripts.recalculate_risk`). Panggilan yang
bertumpuk digabung otomatis. Respons `{"accepted": true}`.

### Menjadwalkan di Railway

Buat **Cron Job** (Service → Settings → Cron Schedule) yang menjalankan `curl` ke backend, atau layanan terpisah dengan
perintah start berikut. Simpan `INTERNAL_API_TOKEN` sebagai variabel (Service Variables) di backend **dan** di cron job.

| Tujuan | Jadwal (UTC) | Perintah |
|---|---|---|
| Hitung ulang skor (menyegarkan bobot umur kejadian) | `0 */6 * * *` | `curl -fsS -X POST -H "X-Internal-Token: $INTERNAL_API_TOKEN" "$BACKEND_URL/internal/recalculate-risk"` |
| Proses ulang laporan yatim | `*/30 * * * *` | `curl -fsS -X POST -H "X-Internal-Token: $INTERNAL_API_TOKEN" "$BACKEND_URL/internal/reprocess"` |

Alternatif tanpa HTTP: cron job Railway yang menjalankan `python -m app.scripts.recalculate_risk` /
`python -m app.scripts.reprocess_reports` dari folder `backend/` dengan variabel lingkungan yang sama (skrip CLI tetap ada).
Tetapkan `BACKEND_URL` ke URL publik backend. Jangan jadwalkan lebih sering dari kebutuhan: proses ulang memakai kuota Gemini.

---

## Nama wilayah pada skor risiko (`/risk/score`, `/risk/heatmap`, `/route/check`)

Sel grid skor kini punya nama wilayah nyata = **kecamatan terdekat** dari pusat sel (dihitung saat perhitungan ulang skor,
bukan saat dibaca; tanpa panggilan jaringan). Field yang ditambahkan (field lama tidak berubah):

| Field | Arti |
|---|---|
| `area_name` | Label grid netral, mis. `Area -7.815, 110.395` (kunci teknis, tetap ada). |
| `place_name` | `"Kec. Gondokusuman"`, atau `null` bila sel jauh (> 8 km) dari kecamatan mana pun / belum dihitung ulang. Nama kembar diberi keterangan: `"Kec. Jetis (Kota Yogyakarta)"`. |
| `label` | **Yang sebaiknya ditampilkan**: `place_name` bila ada, selain itu `area_name`. Selalu terisi. |

Berlaku pada: `GET /risk/score` (objek utama), tiap elemen `cells[]` pada `GET /risk/heatmap`, dan tiap elemen
`areas_to_avoid[]` / `areas_to_watch[]` pada `POST /route/check`. Beberapa sel dapat memakai `place_name` yang sama
(satu kecamatan mencakup banyak sel ±1 km); tampilkan `label` apa adanya atau kelompokkan di UI bila perlu. Data tetap agregat:
tanpa deskripsi, koordinat, atau jalan dari laporan individual.

---

## `GET /risk/summary`

Ringkasan skor **per kecamatan** untuk satu bucket jam, urut skor tertinggi — untuk daftar "wilayah teratas" tanpa
mengulang nama kecamatan yang sama per sel. Publik, di-cache server 60 dtk (`Cache-Control: public, max-age=30`).

Query: `time_bucket` = `dini_hari` | `pagi` | `siang` | `sore` | `malam` (opsional; bawaan: bucket saat ini).

```json
{
  "time_bucket": "malam",
  "regions": [
    {"kecamatan_kode": "34.04.06", "place_name": "Kec. Depok", "label": "Kec. Depok",
     "risk_score": 7.5, "risk_level": "tinggi", "cell_count": 2, "incident_count": 7}
  ],
  "unassigned_cell_count": 1,
  "updated_at": "2026-09-20T06:30:00+00:00"
}
```

`risk_score` = skor akhir **tertinggi** di antara sel kecamatan itu (sudah termasuk pengali musim Ramadan), `risk_level`
dari skor itu, `incident_count` = total insiden kontribusi seluruh sel. Urutan: skor ↓, insiden ↓, nama. Sel yang belum
punya kecamatan (belum dihitung ulang / terlalu jauh dari kecamatan mana pun) tidak masuk `regions` dan dihitung di
`unassigned_cell_count`. Tidak ada koordinat sel, label grid, maupun data individu.

---

## Pencarian tempat: `GET /geo/search` dan `GET /geo/reverse`

Token Mapbox **tidak** pernah ke frontend; frontend memanggil dua endpoint ini. Batas per-IP terpisah dari laporan dan cek
rute (`GEO_SEARCH_RATE_LIMIT_MAX_REQUESTS` per `GEO_SEARCH_RATE_LIMIT_WINDOW_SECONDS`, bawaan 60/60 dtk → `429`).

### `GET /geo/search?q=<kata kunci>&limit=5`

Autocomplete tempat di DIY. `q` minimal 3 karakter (setelah spasi dirapikan), maks 100; `limit` 1–10 (bawaan 5).
**Tambahkan debounce ~300 ms di klien.** Hasil di-cache server 10 menit (LRU); kata kunci tidak pernah dicatat di log.
Semua hasil dijamin berada di DIY.

**Pencarian berlapis** — tiap lapisan menambah hasil berurutan prioritas, sampai `limit` terpenuhi:

| Prioritas | `source` | Asal | Catatan |
|---|---|---|---|
| 1 | `landmark` | Daftar tempat populer DIY yang dikurasi manual (`backend/data/landmarks.json`: kampus, SMA, stasiun/halte, bandara, wisata, pasar, rumah sakit, mal, jalan & kawasan ikonik, …) | Mengenali singkatan/ejaan lain: `UGM`, `YIA`, `Tugu Jogja`, `Stasiun Tugu`, `Kraton`, `jl malioboro`. Tanpa panggilan jaringan. |
| 2 | `photon` | [Photon](https://photon.komoot.io) (data OpenStreetMap), dibatasi bbox DIY | Bagus untuk nama usaha/tempat (kafe, hotel, …). `category` berisi jenis OSM (`cafe`, `hotel`, …). Server publiknya **tidak stabil**. |
| 3 | `nominatim` | [Nominatim](https://nominatim.openstreetmap.org) (data OpenStreetMap), `format=jsonv2`, dibatasi bbox DIY | **Hanya** (a) penyelesaian teks akhir asal/tujuan `POST /route/check` dan (b) autocomplete **saat Photon gagal**. Maks 1 permintaan/detik (pembatas dalam proses; autocomplete yang tidak kebagian giliran dilewati, penyelesaian rute menunggu paling lama 1,5 dtk), cache 30 menit, timeout 3 dtk, jeda 60 dtk setelah gagal. |
| 4 | `wilayah` | Nama kecamatan/desa dari tabel `areas` | Koordinat = titik tengah wilayah. `category` = `kecamatan` / `kelurahan` / `desa`. |
| 5 | `mapbox` | Mapbox Geocoding | **Cadangan terakhir**: hanya dipanggil bila lapisan 1–4 menghasilkan kurang dari `GEO_MAPBOX_FALLBACK_MIN_RESULTS` (bawaan 1 = hanya bila kosong). Dari 5 kandidat dipilih yang pertama valid di DIY. |

Dua hasil dianggap duplikat bila jaraknya < 150 m **dan** namanya mirip; yang berprioritas lebih tinggi dipertahankan.

```json
{
  "count": 2,
  "degraded": false,
  "results": [
    {"label": "Universitas Gadjah Mada", "place_name": "Universitas Gadjah Mada",
     "latitude": -7.7716, "longitude": 110.3775, "source": "landmark", "category": "kampus"},
    {"label": "Kopi Klotok", "place_name": "Kopi Klotok, Pakem, Sleman",
     "latitude": -7.6850, "longitude": 110.4160, "source": "photon", "category": "cafe"}
  ]
}
```

| Field | Keterangan |
|---|---|
| `source` | `landmark` \| `photon` \| `nominatim` \| `wilayah` \| `mapbox` — asal data (bisa dipakai untuk ikon/ketelitian). |
| `category` | Jenis tempat bila diketahui, selain itu `null`. |
| `place_name` | Untuk `landmark` hanya nama tempat (kecamatan sengaja tidak ditebak). |
| `degraded` | `true` bila ada layanan eksternal (Photon/Nominatim/Mapbox) yang gagal atau dilewati sehingga hasil mungkin kurang lengkap; respons `Cache-Control: no-store` dan tidak di-cache server. |

**Gagalnya layanan eksternal bukan error**: Photon mati/lambat (batas 3 dtk) → dilewati dan dijeda 60 dtk
(`GEO_PHOTON_COOLDOWN_SECONDS`) supaya pencarian berikutnya tidak menunggu; hasil dari lapisan lain tetap dikembalikan. Bila
semua lapisan gagal, respons `200` dengan `{"count": 0, "results": [], "degraded": true}` — tampilkan "tidak ditemukan / coba lagi".
Server publik Photon dan Nominatim meminta pemakaian wajar dan `User-Agent` yang jelas dengan kontak: isi lewat
`GEO_PHOTON_USER_AGENT` dan `GEO_NOMINATIM_USER_AGENT` (atau arahkan `GEO_PHOTON_URL` / `GEO_NOMINATIM_URL` ke server
milik sendiri; `GEO_PHOTON_ENABLED=false` / `GEO_NOMINATIM_ENABLED=false` mematikannya). Data © kontributor OpenStreetMap (ODbL).

Error: `422` (q kurang dari 3 karakter), `429`. Pilihan pengguna dikirim ke `POST /route/check` sebagai
`{"latitude": ..., "longitude": ...}` (bukan teks).

### `GET /geo/reverse?lat=<>&lon=<>` — jalur "pilih titik di peta" (pin drop) dan GPS

Dipanggil klien setelah pengguna **menjatuhkan pin di peta** atau memakai GPS, untuk menampilkan label wilayah titik itu
dan memastikan titiknya di DIY. Dihitung dari data wilayah sendiri — **bukan alamat presisi**, tanpa Mapbox, dan koordinat
**tidak digemakan** di respons maupun log. Batas laju sama dengan `/geo/search`.

```json
{"label": "Kec. Depok, Kabupaten Sleman", "kecamatan_kode": "34.04.06", "in_diy": true}
```

| Field | Keterangan |
|---|---|
| `label` | Kecamatan dengan titik pusat terdekat + kabupaten/kota. Dekat perbatasan antarkecamatan bisa berbeda dari batas administratif — tampilkan sebagai "sekitar …". |
| `kecamatan_kode` | Kode kecamatan (cocok dengan `GET /areas`), `null` bila tidak ada kecamatan dalam 8 km. |
| `in_diy` | `false` bila titik di luar DIY. Respons tetap `200` dengan `{"label": "Di luar wilayah DIY", "kecamatan_kode": null, "in_diy": false}`: **tolak titik itu di klien** dan minta pengguna memilih ulang. |

Bila data wilayah tak terbaca atau kecamatan terdekat > 8 km: `{"label": "Lokasi Anda (Yogyakarta)", "kecamatan_kode": null,
"in_diy": true}` (alur tidak terhenti). `422` hanya untuk parameter tidak valid (lat/lon kosong atau di luar rentang bumi).

Alur klien: pengguna menjatuhkan pin → `GET /geo/reverse` (tampilkan `label`, tolak bila `in_diy=false`) → saat mengecek
rute kirim `{"latitude": ..., "longitude": ...}` ke `POST /route/check` (tidak perlu teks).

---

## `POST /route/check` — Cek Rute Aman

Menelusuri jalan-jalan yang dilalui rute mengemudi asal → tujuan, memeriksa riwayat kejadian terskor di sekitar jalur pada
**jam perjalanan** (per titik), lalu menilai `aman` / `waspada` / `berisiko_tinggi` dengan alasan yang jelas. Publik, tanpa login.
Batas per-IP: `ROUTE_CHECK_RATE_LIMIT_MAX_REQUESTS` per `ROUTE_CHECK_RATE_LIMIT_WINDOW_SECONDS` (bawaan 20/600 dtk).
Query opsional `include_narrative=true` menambahkan `narrative` (penjelasan Gemini, hanya untuk rute waspada/berisiko tinggi).

### Request

```json
{
  "origin":      {"latitude": -7.7829, "longitude": 110.3671},
  "destination": {"text": "Condongcatur"},
  "departure_time": "2026-10-28T22:00:00"
}
```

| Field | Keterangan |
|---|---|
| `origin`, `destination` | Salah satu dari `{"latitude", "longitude"}` (GPS / hasil `/geo/search`, **disarankan**) atau `{"text"}` (diselesaikan server dengan **pencarian berlapis yang sama** dengan `/geo/search`: landmark > Photon > Nominatim > wilayah > Mapbox, hasil teratas yang valid di DIY; hasil bisa kasar, lihat `location_notes`). Koordinat menang bila keduanya ada. Harus di dalam DIY. |
| `departure_time` | ISO 8601, opsional (bawaan: sekarang). **Tanpa zona waktu = WIB.** Lebih dari 5 menit di masa lalu → `422` (`Waktu berangkat tidak boleh di masa lalu`); maksimal 30 hari ke depan. |

Jam dan musim dinilai **per titik** dari waktu tiba di titik itu (berangkat + durasi), jadi rute yang melewati pergantian jam
atau tengah malam dinilai dengan bucket dan pengali Ramadan yang sesuai di tiap bagiannya.

### Respons `200`

Contoh dari **data uji sintetis** (`backend/tests/route_sample.py`: nama jalan/kecamatan nyata, tetapi *insiden-nya karangan*,
bukan data kejadian sebenarnya). Array koordinat dipotong (`"... N titik lagi"`) agar ringkas; versi **utuh dan valid**:
[`backend/docs/examples/route_check_example.json`](examples/route_check_example.json) (bisa dipakai sebagai mock frontend).

```jsonc
{
  "risk_level": "berisiko_tinggi",
  "max_risk_score": 8.11,
  "areas_to_avoid": [
    {
      "area_name": "Jalan Kaliurang",
      "place_name": "Kec. Depok",
      "label": "Jalan Kaliurang (Kec. Depok)",
      "latitude": -7.75871,
      "longitude": 110.38639,
      "time_bucket": "malam",
      "risk_score": 8.11,
      "risk_level": "tinggi",
      "segment_index": 1
    }
  ],
  "areas_to_watch": [
    {
      "area_name": "Ring Road Utara",
      "place_name": "Kec. Ngaglik",
      "label": "Ring Road Utara (Kec. Ngaglik)",
      "latitude": -7.73685,
      "longitude": 110.3975,
      "time_bucket": "malam",
      "risk_score": 3.59,
      "risk_level": "sedang",
      "segment_index": 2
    }
  ],
  "areas_checked": 65,
  "areas_with_data": 41,
  "origin": {
    "latitude": -7.7829,
    "longitude": 110.3671,
    "place_name": "Kec. Jetis (Kota Yogyakarta)"
  },
  "destination": {
    "latitude": -7.73,
    "longitude": 110.406,
    "place_name": "Kec. Ngaglik"
  },
  "distance_km": 7.5,
  "duration_minutes": 14,
  "departure_time": "2026-09-20T22:00:00+07:00",
  "time_buckets": [
    "malam"
  ],
  "data_coverage": 0.631,
  "data_limited": false,
  "data_note": null,
  "location_notes": [],
  "alternatives": [
    {
      "risk_level": "aman",
      "max_risk_score": 0.0,
      "distance_km": 9.7,
      "duration_minutes": 14,
      "data_coverage": 0.797,
      "data_limited": false,
      "is_lowest_risk": true,
      "extra_minutes": 0,
      "summary": {
        "status": "aman",
        "max_risk_score": 0.0,
        "distance_km": 9.7,
        "duration_minutes": 14,
        "data_coverage": 0.797,
        "data_limited": false,
        "high_exposure_m": 0,
        "medium_exposure_m": 0,
        "incident_count": 0,
        "time_buckets": [
          "malam"
        ]
      },
      "geometry": {
        "type": "LineString",
        "coordinates": [
          [110.3671, -7.7829],
          [110.364, -7.779],
          [110.361, -7.77],
          "... 5 titik lagi"
        ]
      },
      "segments": [
        {
          "index": 0,
          "road_name": "Jalan Mangkubumi",
          "place_name": "Kec. Jetis (Kota Yogyakarta)",
          "start_km": 0.0,
          "end_km": 1.606,
          "length_m": 1606,
          "risk_level": "rendah",
          "risk_score": 0.0,
          "incident_count": 0,
          "dominant_category": null,
          "incident_hours": {},
          "has_nearby_data": false,
          "peak_time_bucket": "malam",
          "geometry": {
            "type": "LineString",
            "coordinates": [
              [110.3671, -7.7829],
              [110.364, -7.779],
              [110.361, -7.77]
            ]
          }
        },
        {
          "index": 1,
          "road_name": "Jalan Magelang",
          "place_name": "Kec. Mlati",
          "start_km": 1.606,
          "end_km": 4.829,
          "length_m": 3224,
          "risk_level": "rendah",
          "risk_score": 0.0,
          "incident_count": 0,
          "dominant_category": null,
          "incident_hours": {},
          "has_nearby_data": true,
          "peak_time_bucket": "malam",
          "geometry": {
            "type": "LineString",
            "coordinates": [
              [110.361, -7.77],
              [110.359, -7.756],
              [110.364, -7.742]
            ]
          }
        },
        {
          "index": 2,
          "road_name": "Ring Road Utara",
          "place_name": "Kec. Ngaglik",
          "start_km": 4.829,
          "end_km": 8.922,
          "length_m": 4092,
          "risk_level": "rendah",
          "risk_score": 0.0,
          "incident_count": 0,
          "dominant_category": null,
          "incident_hours": {},
          "has_nearby_data": true,
          "peak_time_bucket": "malam",
          "geometry": {
            "type": "LineString",
            "coordinates": [
              [110.364, -7.742],
              [110.386, -7.736],
              [110.4, -7.733]
            ]
          }
        },
        {
          "index": 3,
          "road_name": "jalan tanpa nama",
          "place_name": "Kec. Ngaglik",
          "start_km": 8.922,
          "end_km": 9.662,
          "length_m": 740,
          "risk_level": "rendah",
          "risk_score": 0.0,
          "incident_count": 0,
          "dominant_category": null,
          "incident_hours": {},
          "has_nearby_data": true,
          "peak_time_bucket": "malam",
          "geometry": {
            "type": "LineString",
            "coordinates": [
              [110.4, -7.733],
              [110.406, -7.73]
            ]
          }
        }
      ],
      "reasons": [
        "Tidak ada bagian jalur yang melewati area berskor sedang atau tinggi pada jam perjalanan, berdasarkan data kejadian yang tercatat.",
        "Hasil berdasarkan data kejadian yang tercatat dan bukan jaminan keamanan; 80% titik pemeriksaan memiliki data kejadian di sekitarnya.",
        "Lebih rendah risikonya dibanding rute utama, dengan waktu tempuh yang sama."
      ]
    }
  ],
  "safer_alternative_available": true,
  "summary": {
    "status": "berisiko_tinggi",
    "max_risk_score": 8.11,
    "distance_km": 7.5,
    "duration_minutes": 14,
    "data_coverage": 0.631,
    "data_limited": false,
    "high_exposure_m": 250,
    "medium_exposure_m": 750,
    "incident_count": 11,
    "time_buckets": [
      "malam"
    ]
  },
  "geometry": {
    "type": "LineString",
    "coordinates": [
      [110.3671, -7.7829],
      [110.3715, -7.779],
      [110.375, -7.7745],
      "... 5 titik lagi"
    ]
  },
  "segments": [
    {
      "index": 0,
      "road_name": "Jalan Cik Di Tiro",
      "place_name": "Kec. Jetis (Kota Yogyakarta)",
      "start_km": 0.0,
      "end_km": 1.282,
      "length_m": 1282,
      "risk_level": "rendah",
      "risk_score": 0.0,
      "incident_count": 0,
      "dominant_category": null,
      "incident_hours": {},
      "has_nearby_data": false,
      "peak_time_bucket": "malam",
      "geometry": {
        "type": "LineString",
        "coordinates": [
          [110.3671, -7.7829],
          [110.3715, -7.779],
          [110.375, -7.7745]
        ]
      }
    },
    {
      "index": 1,
      "road_name": "Jalan Kaliurang",
      "place_name": "Kec. Depok",
      "start_km": 1.282,
      "end_km": 5.623,
      "length_m": 4341,
      "risk_level": "tinggi",
      "risk_score": 8.11,
      "incident_count": 9,
      "dominant_category": "klitih",
      "incident_hours": {
        "dini_hari": 2,
        "malam": 7
      },
      "has_nearby_data": true,
      "peak_time_bucket": "malam",
      "geometry": {
        "type": "LineString",
        "coordinates": [
          [110.375, -7.7745],
          [110.38, -7.767],
          [110.386, -7.76],
          "... 1 titik lagi"
        ]
      }
    },
    {
      "index": 2,
      "road_name": "Ring Road Utara",
      "place_name": "Kec. Ngaglik",
      "start_km": 5.623,
      "end_km": 7.023,
      "length_m": 1400,
      "risk_level": "sedang",
      "risk_score": 3.59,
      "incident_count": 2,
      "dominant_category": "begal/penodongan",
      "incident_hours": {
        "malam": 2
      },
      "has_nearby_data": true,
      "peak_time_bucket": "malam",
      "geometry": {
        "type": "LineString",
        "coordinates": [
          [110.392, -7.74],
          [110.399, -7.736],
          [110.4025, -7.733]
        ]
      }
    },
    {
      "index": 3,
      "road_name": "jalan tanpa nama",
      "place_name": "Kec. Ngaglik",
      "start_km": 7.023,
      "end_km": 7.533,
      "length_m": 510,
      "risk_level": "rendah",
      "risk_score": 0.0,
      "incident_count": 0,
      "dominant_category": null,
      "incident_hours": {},
      "has_nearby_data": true,
      "peak_time_bucket": "malam",
      "geometry": {
        "type": "LineString",
        "coordinates": [
          [110.4025, -7.733],
          [110.406, -7.73]
        ]
      }
    }
  ],
  "reasons": [
    "Sekitar 250 m jalur melewati area berskor kerawanan tinggi pada jam perjalanan.",
    "Melewati Jalan Kaliurang (Kec. Depok): 9 kejadian tercatat dalam radius 300 m dari jalur, kategori terbanyak klitih, paling sering pada jam malam dan dini hari. Anda diperkirakan melintas pada jam malam.",
    "Melewati Ring Road Utara (Kec. Ngaglik): 2 kejadian tercatat dalam radius 300 m dari jalur, kategori terbanyak begal/penodongan, paling sering pada jam malam. Anda diperkirakan melintas pada jam malam.",
    "Tersedia rute alternatif dengan risiko lebih rendah, dengan waktu tempuh yang sama."
  ],
  "recommended_route": 1,
  "narrative": null
}
```

### Bentuk geometri (penting untuk menggambar peta)

`geometry` (rute) dan `segments[].geometry` (tiap ruas) berupa **GeoJSON `LineString`**:

```json
{"type": "LineString", "coordinates": [[110.3671, -7.7829], [110.3715, -7.779]]}
```

- **Urutan koordinat = `[bujur, lintang]` (`[longitude, latitude]`)** — sesuai GeoJSON/Mapbox GL. Hati-hati: `latitude`/`longitude`
  di field lain (`origin`, `areas_to_*`) berupa objek bernama, bukan array.
- Sudah **dijarangkan** (Douglas-Peucker, toleransi 15 m) dan dibulatkan 5 desimal (~1 m): respons contoh di atas (rute utama + 1 alternatif) ±6,5 KB.
- Garis ruas bersambung ujung-ke-ujung dan berurutan sesuai `segments[].index`. Untuk mewarnai garis, satu `source` GeoJSON per
  ruas (atau satu `FeatureCollection` dari `segments`) dengan warna dari `risk_level`. Contoh Mapbox GL:

```ts
map.addSource("rute", { type: "geojson", data: {
  type: "FeatureCollection",
  features: route.segments.map((s) => ({ type: "Feature", geometry: s.geometry, properties: { level: s.risk_level } })),
}});
map.addLayer({ id: "rute-garis", type: "line", source: "rute", paint: { "line-width": 6,
  "line-color": ["match", ["get", "level"], "tinggi", "#f87171", "sedang", "#fbbf24", "#34d399"] } });
```

### Field respons

| Field | Arti |
|---|---|
| `risk_level` / `summary.status` | `aman` \| `waspada` \| `berisiko_tinggi`. "aman" berarti **tidak ada paparan yang memenuhi syarat di data yang tercatat — bukan jaminan keamanan**. |
| `max_risk_score` | Skor 0–10 tertinggi di jalur (skala sama dengan heatmap; sedang ≥ 3, tinggi ≥ 7). |
| `summary` | `status`, `max_risk_score`, `distance_km`, `duration_minutes`, `data_coverage`, `data_limited`, `high_exposure_m` (panjang jalur berlevel tinggi), `medium_exposure_m` (sedang atau lebih), `incident_count` (insiden berbeda yang berkontribusi — agregat), `time_buckets`. |
| `geometry` | Garis rute utama (GeoJSON, lihat di atas). |
| `segments[]` | Ruas jalan berurutan (langkah berurutan bernama sama digabung; tanpa nama = `"jalan tanpa nama"`): `index`, `road_name`, `place_name` ("Kec. X"), `start_km`/`end_km`/`length_m`, `risk_level` (`rendah`\|`sedang`\|`tinggi`), `risk_score`, `incident_count`, `dominant_category`, `incident_hours` (bucket jam kejadian **historis** → jumlah), `has_nearby_data`, `peak_time_bucket` (jam Anda melintas di titik skor tertinggi), `geometry`. |
| `reasons[]` | Alasan netral berbahasa Indonesia, siap ditampilkan (dibuat deterministik dari data, bukan oleh AI). Selalu disertai catatan "bukan jaminan" untuk rute aman / tanpa data. |
| `alternatives[]` | Rute alternatif Mapbox (maks 2) dengan struktur serupa: `risk_level`, `max_risk_score`, `distance_km`, `duration_minutes`, `data_coverage`, `data_limited`, `is_lowest_risk`, `extra_minutes` (selisih menit tampil vs rute utama; negatif = lebih cepat), `summary`, `geometry`, `segments`, `reasons`. |
| `recommended_route` | `0` = rute utama paling rendah risikonya; `i` ≥ 1 = alternatif ke-*i* (1-based, urutan `alternatives`) yang disarankan. `safer_alternative_available` = `recommended_route != 0`. |
| `data_coverage`, `data_limited`, `data_note` | Cakupan data: bagian titik cek yang punya data kejadian (jam apa pun) dalam 1,5 km. `data_limited` bila tidak ada data sama sekali; `data_note` menjelaskannya. "Tidak ada kejadian dekat" ≠ "tidak ada data". |
| `origin`, `destination` | Titik yang dipakai + `place_name` (selalu terisi: nama Mapbox, teks yang Anda ketik, nama kecamatan, atau label grid). |
| `location_notes[]` | Catatan bila geocoding teks diragukan (jatuh di pusat kota/kabupaten). Tidak ada untuk titik koordinat/GPS. |
| `narrative` | Penjelasan Gemini (opsional) atau `null`. |

### Aturan status (deterministik)

| Panjang jalur berlevel **tinggi** | Panjang jalur **sedang atau lebih** | Skor maks | Status |
|---|---|---|---|
| ≥ 200 m | — | ≥ 7.0 | `berisiko_tinggi` |
| 1–199 m | — | 7.0–8.49 | `waspada` (tinggi pendek) |
| apa pun > 0 | — | ≥ 8.5 | `berisiko_tinggi` (skor kritis) |
| 0 | ≥ 400 m | 3.0–6.99 | `waspada` |
| 0 | < 400 m | < 7 | `aman` (ruas sedang tetap tampil di `segments`/`areas_to_watch`) |

Rute yang melintasi titik berskor tinggi **tidak pernah** `aman`. Semua ambang dapat disetel lewat env (`ROUTE_*`). Skor tiap titik =
insiden dalam radius 300 m, dibobot jarak (linear) × kebaruan × kesesuaian jam tiba (jam sama penuh, jam bertetangga ½) lalu
pengali Ramadan; fungsi jenuh yang sama dengan heatmap.

### Perubahan dari versi sebelumnya (kompatibilitas)

Field lama **tetap ada**, tetapi maknanya bergeser dari sel grid 1,1 km ke ruas jalan:

- `areas_to_avoid[]` / `areas_to_watch[]`: kini **ruas jalan** berlevel tinggi / sedang. `area_name` = nama jalan, `place_name` =
  "Kec. X", `label` = teks tampil, `latitude`/`longitude` = **titik tengah ruas** di jalur (bukan lokasi insiden), `segment_index`
  menunjuk ke `segments[]`. Maks 5 entri.
- `areas_checked` / `areas_with_data`: kini jumlah **titik pemeriksaan** (± tiap 125 m) dan yang punya data di sekitarnya.
- `time_buckets`: bucket jam yang dilalui, urut sepanjang rute.
- Waktu berangkat di masa lalu > 5 menit kini ditolak (`422`).

### Privasi

Respons hanya memuat **agregat per ruas** (jumlah, kategori umum dari kosakata tetap, sebaran bucket jam). Tidak ada koordinat atau
deskripsi insiden individual; koordinat yang dikeluarkan hanya titik di jalur rute Anda sendiri. Kategori dipetakan ke kosakata
tetap: `klitih`, `penyerangan`, `bentrok antar kelompok`, `begal/penodongan`, `kejadian mencurigakan`, `pengrusakan`, `lainnya`.
Kueri rute tidak disimpan; log akses server tidak memuat IP maupun query string.

### Error

| Status | `detail` |
|---|---|
| 422 | `Lokasi asal tidak ditemukan di wilayah Yogyakarta. Coba sertakan nama kecamatan atau "Yogyakarta".` |
| 422 | `Titik tujuan berada di luar wilayah Yogyakarta.` |
| 422 | `Rute antara kedua titik tidak ditemukan. Coba titik yang lebih dekat ke jalan.` |
| 422 | `Waktu berangkat tidak boleh di masa lalu` |
| 429 | `Terlalu banyak pemeriksaan rute dari sumber ini, coba lagi nanti.` |
| 503 | `Layanan peta/rute sedang tidak tersedia, silakan coba lagi.` |
| 502 | `Pemeriksaan rute gagal diproses, silakan coba lagi.` |

Waktu respons: analisis di server diukur 0,4 dtk untuk 3 rute × ±9 km × 1.000 insiden (di komputer pengembangan, data di memori).
Selebihnya adalah waktu panggilan Mapbox (Directions, plus geocoding bila titik berupa teks) yang bergantung jaringan dan
belum diukur; titik berupa koordinat menghemat satu panggilan per titik.
