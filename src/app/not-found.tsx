import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="container-x flex min-h-screen flex-col items-center justify-center pb-16 pt-32 text-center">
      <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">Kesalahan 404</p>
      <h1 className="mt-3 font-display text-3xl font-bold tracking-tight text-white sm:text-5xl">Halaman tidak ditemukan</h1>
      <p className="mt-4 max-w-md text-base leading-normal text-zinc-500">
        Alamat yang Anda buka tidak ada atau sudah dipindahkan. Coba salah satu halaman utama berikut.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Link href="/" className="btn-primary">
          Ke beranda
        </Link>
        <Link href="/rute" className="btn-ghost">
          Cek Rute
        </Link>
        <Link href="/peta" className="btn-ghost">
          Peta Kerawanan
        </Link>
      </div>
    </div>
  );
}
