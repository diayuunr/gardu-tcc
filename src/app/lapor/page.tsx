import type { Metadata } from 'next';

import Reveal from '@/components/Reveal';
import ReportForm from '@/components/report/ReportForm';

export const metadata: Metadata = {
  title: 'Lapor Kejadian',
  description: 'Laporkan kejadian jalanan secara anonim. Tanpa akun, tanpa nama, tanpa nomor telepon.',
};

export default function LaporPage() {
  return (
    <div className="container-x min-h-screen pb-24 pt-32">
      <div className="mx-auto max-w-3xl">
        <Reveal>
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">Lapor Kejadian</p>
          <h1 className="mt-3 font-display text-3xl font-bold text-white sm:text-4xl">Ceritakan apa yang kamu lihat.</h1>
          <p className="mt-3 text-zinc-500">
            Laporan bersifat <span className="text-emerald-300">anonim</span>. Tidak ada nama, nomor telepon, atau akun yang
            dikirim melalui formulir ini.
          </p>
        </Reveal>

        <Reveal delay={0.15}>
          <ReportForm />
        </Reveal>
      </div>
    </div>
  );
}
