'use client';

import { RefreshCw } from 'react-feather';

import { LOADING_STEPS } from '@/hooks/useRouteCheck';

/** Keadaan awal: panduan singkat sebelum pemeriksaan pertama. */
export function RouteIdlePanel() {
  return (
    <section className="glass-card p-5 sm:p-6" aria-labelledby="rute-panduan">
      <h2 id="rute-panduan" className="font-display text-lg font-semibold text-white">
        Bagaimana hasilnya dibaca
      </h2>

      <ul className="mt-3 space-y-2 text-sm leading-relaxed text-zinc-400">
        <li>Pilih titik asal dan tujuan, lalu tekan &quot;Periksa Risiko Rute&quot;.</li>
        <li>
          Rute digambar per ruas jalan dan diwarnai menurut tingkat risiko tercatat pada jam berangkat: hijau rendah,
          kuning sedang, merah tinggi.
        </li>
        <li>Ketuk ruas di peta atau di daftar untuk melihat rinciannya. Bila ada rute alternatif, Anda bisa membandingkannya.</li>
      </ul>

      <p className="mt-4 text-xs leading-relaxed text-zinc-500">
        Hasil berdasarkan data kejadian yang tercatat dan bukan jaminan keamanan.
      </p>
    </section>
  );
}

/** Sedang memeriksa: langkah bergulir + kerangka hasil. */
export function RouteLoadingPanel({ step }: { step: number }) {
  return (
    <section className="glass-card p-5 sm:p-6" aria-busy="true" aria-labelledby="rute-memuat">
      <h2 id="rute-memuat" className="font-display text-lg font-semibold text-white">
        Memeriksa rute...
      </h2>

      <ol className="mt-4 space-y-3" role="status" aria-live="polite">
        {LOADING_STEPS.map((label, index) => {
          const done = index < step;
          const current = index === step;

          return (
            <li
              key={label}
              className={`flex items-center gap-3 text-sm ${current ? 'text-zinc-100' : done ? 'text-zinc-400' : 'text-zinc-600'}`}
              aria-current={current ? 'step' : undefined}
            >
              <span
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] ${
                  done ? 'border-emerald-400/60 bg-emerald-400/20 text-emerald-300' : current ? 'border-emerald-400/60' : 'border-line'
                }`}
                aria-hidden="true"
              >
                {done ? '✓' : current ? (
                  <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400 motion-reduce:animate-none" />
                ) : null}
              </span>
              {label}
              {current && <span className="sr-only"> (sedang berlangsung)</span>}
            </li>
          );
        })}
      </ol>

      <div className="mt-6 space-y-3" aria-hidden="true">
        <div className="h-16 animate-pulse rounded-2xl bg-white/5 motion-reduce:animate-none" />
        <div className="h-4 w-3/4 animate-pulse rounded bg-white/5 motion-reduce:animate-none" />
        <div className="h-4 w-1/2 animate-pulse rounded bg-white/5 motion-reduce:animate-none" />
      </div>

      <p className="mt-4 text-xs text-zinc-500">Biasanya beberapa detik; bisa lebih lama saat layanan peta sibuk.</p>
    </section>
  );
}

/** Pemeriksaan gagal: pesan Indonesia dari backend/klien + tombol coba lagi. */
export function RouteErrorPanel({
  message,
  kind,
  onRetry,
}: {
  message: string;
  kind: string;
  onRetry: () => void;
}) {
  const hint =
    kind === 'validation'
      ? 'Periksa titik asal, tujuan, dan waktu berangkat, lalu coba lagi.'
      : kind === 'rate_limit'
        ? 'Batas pemeriksaan sementara tercapai. Tunggu beberapa menit sebelum mencoba lagi.'
        : kind === 'unavailable'
          ? 'Layanan peta/rute sedang bermasalah. Pilihan titik Anda tetap tersimpan di formulir.'
          : kind === 'network' || kind === 'timeout'
            ? 'Pastikan koneksi internet Anda aktif. Pilihan titik Anda tetap tersimpan di formulir.'
            : 'Pilihan titik Anda tetap tersimpan di formulir.';

  return (
    <section className="rounded-3xl border border-red-400/30 bg-red-400/5 p-5 sm:p-6" role="alert">
      <h2 className="font-display text-lg font-semibold text-red-200">Rute belum dapat diperiksa</h2>
      <p className="mt-2 text-sm leading-relaxed text-zinc-200">{message}</p>
      <p className="mt-2 text-xs leading-relaxed text-zinc-400">{hint}</p>

      {kind !== 'validation' && kind !== 'rate_limit' && (
        <button type="button" onClick={onRetry} className="btn-ghost mt-4 !px-5 !py-2">
          <RefreshCw size={14} aria-hidden="true" />
          Coba lagi
        </button>
      )}
    </section>
  );
}
