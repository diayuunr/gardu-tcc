# Daftar uji manual frontend Gardu

Uji ini melengkapi tes otomatis (`npm test`, fungsi murni) dan pengecekan statis (`npx tsc --noEmit`, `npm run lint`,
`npm run build`). Isi kolom hasil dengan ✅ / ❌ dan catatan.

**Prasyarat:** backend menyala (`backend/`, uvicorn), `.env.local` terisi (lihat `ENV.md`), data demo termuat, `npm run dev`.
Uji di lebar **375 px**, **768 px**, dan **1280 px** (DevTools → mode perangkat). Konsol peramban tidak boleh memuat error
merah maupun data laporan/koordinat.

## Umum
| # | Langkah | Harapan | Hasil |
|---|---|---|---|
| U1 | Tab baru, buka `/` | Pembuka ±0,7 dtk muncul sekali; muat ulang / pindah halaman tidak mengulang | |
| U2 | Buka alamat acak, mis. `/xyz` | Halaman 404 kustom dengan tombol ke beranda, Cek Rute, Peta | |
| U3 | Judul tab tiap halaman | "Cek Rute \| Gardu", "Peta Kerawanan \| Gardu", dst. | |
| U4 | Navbar desktop dan menu mobile | Semua tautan berfungsi, tak ada tautan mati; "Histori Laporan" → `/laporan` | |
| U5 | Footer | Tautan berfungsi; "Moderator" → `/admin` | |
| U6 | Semua halaman di 375/768/1280 px | Tidak ada scroll horizontal, teks terpotong, atau tombol bertumpuk | |
| U7 | Aktifkan *reduce motion* di OS | Animasi dekoratif (blob, floaty, marquee) berhenti; fungsi tetap jalan | |
| U8 | Matikan backend, buka tiap halaman | Pesan error ramah + "Coba lagi"; halaman tidak crash | |
| U9 | Navigasi papan ketik (Tab) | Fokus terlihat; combobox, dialog, dan tombol dapat dioperasikan tanpa tetikus | |

## Landing `/`
| # | Langkah | Harapan | Hasil |
|---|---|---|---|
| L1 | Tiga angka hero | Terisi (laporan masuk, kecamatan berskor, area berskor) + keterangan "termasuk data simulasi" | |
| L2 | Kartu status kawasan | Skor + lencana + wilayah; periode tanpa data → "Belum ada data … bukan berarti aman" | |
| L3 | Backend mati | Angka "-" dan kartu pesan error + "Coba lagi" | |

## Cek Rute `/rute`
| # | Langkah | Harapan | Hasil |
|---|---|---|---|
| R1 | Ketik ≥3 huruf di asal | Saran muncul (landmark/jalan), bisa dipilih dengan klik dan panah+Enter | |
| R2 | Tombol lokasi saya | Izin ditolak → pesan jelas; berhasil → titik di dalam DIY; di luar DIY ditolak | |
| R3 | Pilih titik di peta | Titik terisi dengan nama dari reverse geocode | |
| R4 | Contoh rute 1: RSUP Dr. Sardjito → Kaliurang, 21.00 | Hasil waspada/berisiko tinggi; peta berwarna per ruas; alasan tampil | |
| R5 | Contoh rute 2: Prawirotaman → Parangtritis, 02.00 | Hasil tampil, ruas berwarna, alternatif (bila ada) dapat dipilih | |
| R6 | Contoh rute 3: Terminal Jombor → Sleman City Hall, 13.00 | Hasil siang hari lebih rendah dibanding malam | |
| R7 | Asal = tujuan; waktu masa lalu; waktu >30 hari | Pesan validasi per field | |
| R8 | Klik ruas di peta / daftar ruas | Popup/ringkasan ruas sinkron | |
| R9 | Ubah titik setelah hasil muncul | Hasil lama ditandai usang | |

## Lapor `/lapor`
| # | Langkah | Harapan | Hasil |
|---|---|---|---|
| P1 | Kirim kosong | Error per field, fokus ke field pertama yang salah | |
| P2 | Dropdown kabupaten → kecamatan → kelurahan | Berjenjang dari backend, anak tereset saat induk berubah | |
| P3 | Isi jalan dengan email/nomor telepon | Ditolak dengan pesan privasi | |
| P4 | Waktu: "Sekarang" dan "Pilih waktu" (masa depan ditolak) | Sesuai | |
| P5 | Kirim valid | Layar sukses dengan nomor GRD dan status; tidak ada data pribadi ditanyakan | |
| P6 | Kirim berulang cepat (rate limit 429) | Pesan "terlalu banyak permintaan", formulir tidak hilang | |

## Peta Kerawanan `/peta`
| # | Langkah | Harapan | Hasil |
|---|---|---|---|
| M1 | Pilih tiap periode jam | Peta dan daftar "Skor tertinggi" berubah; tak ada nama kecamatan kembar | |
| M2 | Klik lingkaran sel | Popup skor; sel tanpa kejadian: "Skor berasal dari kejadian tercatat di area sekitarnya." | |
| M3 | Klik kecamatan di daftar | Peta zoom ke kecamatan itu | |
| M4 | Tanpa token Mapbox | Peta diganti pesan; tabel/daftar tetap ada | |

## Histori Laporan `/laporan`
| # | Langkah | Harapan | Hasil |
|---|---|---|---|
| H1 | Statistik dan kartu laporan | Terisi; hanya nomor, status, wilayah, jam, kategori (tanpa isi/koordinat) | |
| H2 | Paginasi | Maju/mundur, tombol nonaktif di ujung, gulir ke daftar | |
| H3 | Berita terkait | Tautan terbuka di tab baru; gambar gagal muat → kartu tetap tampil | |

## Sumber daya `/sumber-daya`
| # | Langkah | Harapan | Hasil |
|---|---|---|---|
| S1 | Kontak | Nomor telepon dapat ditekan di mobile; **verifikasi nomor sebelum demo** (Satpol PP DIY, Dinas Sosial DIY) | |

## Moderasi `/admin`
| # | Langkah | Harapan | Hasil |
|---|---|---|---|
| A1 | Tanpa login | Formulir masuk; sumber halaman memuat `noindex` | |
| A2 | Kredensial salah / jaringan mati | Pesan generik / pesan koneksi | |
| A3 | Akun Supabase yang bukan moderator | "Akses ditolak" + Keluar | |
| A4 | Akun moderator | Nama tampil, antrean "Perlu tinjauan" terisi | |
| A5 | Setujui / Tolak / Kembalikan | Dialog konfirmasi → pesan hasil → daftar dimuat ulang; ulangi → "tidak ada perubahan" | |
| A6 | Token kedaluwarsa (hapus sesi di devtools) lalu aksi | Kembali ke layar masuk dengan pesan sesi berakhir | |
| A7 | Cek tab Network | Token hanya di header `Authorization`, tidak di URL; tidak ada service-role key | |

## Privasi dan keamanan (lintas halaman)
- Konsol tidak memuat isi laporan, koordinat, atau kata kunci pencarian.
- Bundel dan tab Network tidak memuat kunci selain empat variabel `NEXT_PUBLIC_*`.
- Teks tidak menjanjikan keamanan; keterangan "bukan jaminan" dan "data simulasi" tampil di tempatnya.
