# Variabel lingkungan frontend

Frontend (Next.js, folder `src/`) hanya memakai **empat** variabel, semuanya berawalan `NEXT_PUBLIC_` sehingga **terlihat
di peramban**. Karena itu jangan pernah mengisinya dengan rahasia: service role key Supabase, token Gemini, dan
`INTERNAL_API_TOKEN` backend **tidak boleh** ada di sini.

Isi di `.env.local` (lokal, tidak di-commit) dan di pengaturan Environment Variables Vercel (produksi). Nilai tidak
dicantumkan di dokumen ini.

| Variabel | Dipakai untuk | Bila kosong |
|---|---|---|
| `NEXT_PUBLIC_BACKEND_URL` | URL dasar backend FastAPI, mis. `http://localhost:8000` (lokal) atau URL Railway (produksi). Tanpa garis miring di akhir. | Bawaan `http://localhost:8000`. Di produksi **wajib diisi**, kalau tidak semua halaman gagal terhubung. |
| `NEXT_PUBLIC_MAPBOX_TOKEN` | Peta (peta kerawanan dan Cek Rute) memakai Mapbox GL. Gunakan token **publik** (`pk.…`) dan batasi URL pemakainya di dashboard Mapbox. | Peta tidak dimuat; halaman menampilkan pesan dan data tetap tersedia sebagai daftar/tabel. |
| `NEXT_PUBLIC_SUPABASE_URL` | URL proyek Supabase, hanya untuk **login moderator** (`/admin`) lewat Supabase Auth. | Halaman moderasi menampilkan pesan konfigurasi belum lengkap. |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Kunci publik (publishable/anon) Supabase untuk Supabase Auth. **Bukan** service role key. | Sama seperti di atas. |

Catatan:

- Frontend tidak lagi membaca atau menulis tabel Supabase secara langsung. Semua data laporan, peta, dan rute lewat API backend
  (`backend/docs/API.md`); Supabase hanya dipakai untuk autentikasi moderator.
- Backend perlu mengizinkan origin frontend lewat `CORS_ALLOW_ORIGINS` (lihat `backend/.env.example`).
- Perubahan nilai `NEXT_PUBLIC_*` baru berlaku setelah server dev dijalankan ulang / aplikasi dibangun ulang, karena nilainya
  disisipkan saat build.
