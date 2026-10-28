'use client';

import Link from 'next/link';

/** Batas error halaman. Sengaja tidak menampilkan atau mencatat rincian error (bisa memuat data laporan). */
export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="container-x flex min-h-screen flex-col items-center justify-center pb-16 pt-32 text-center">
      <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">Terjadi kesalahan</p>
      <h1 className="mt-3 font-display text-3xl font-bold tracking-tight text-white sm:text-5xl">Halaman gagal dimuat</h1>
      <p className="mt-4 max-w-md text-base leading-normal text-zinc-500" role="alert">
        Ada masalah saat menampilkan halaman ini. Silakan coba lagi; bila berulang, kembali ke beranda.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <button type="button" onClick={reset} className="btn-primary">
          Coba lagi
        </button>
        <Link href="/" className="btn-ghost">
          Ke beranda
        </Link>
      </div>
    </div>
  );
}
