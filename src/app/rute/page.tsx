import type { Metadata } from 'next';

import Reveal from '@/components/Reveal';
import RouteChecker from '@/components/route/RouteChecker';

export const metadata: Metadata = {
  title: 'Cek Rute',
  description:
    'Periksa riwayat kejadian tercatat di sepanjang rute Anda pada jam berangkat. Panduan kewaspadaan, bukan jaminan keamanan.',
};

export default function RutePage() {
  return (
    <div className="container-x min-h-screen pb-24 pt-32">
      <Reveal>
        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">Cek Rute</p>

        <h1 className="mt-3 font-display text-3xl font-bold text-white sm:text-4xl">Cek rute sebelum berangkat.</h1>

        <p className="mt-2 max-w-2xl text-zinc-500">
          Gardu menelusuri ruas jalan yang Anda lewati dan memeriksa riwayat kejadian tercatat di sekitarnya pada jam
          keberangkatan. Hasilnya panduan kewaspadaan, bukan jaminan keamanan.
        </p>
      </Reveal>

      <div className="mt-8">
        <RouteChecker />
      </div>
    </div>
  );
}
