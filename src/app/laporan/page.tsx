import type { Metadata } from 'next';

import NewsSection from '@/components/history/NewsSection';
import ReportHistory from '@/components/history/ReportHistory';
import Reveal from '@/components/Reveal';

export const metadata: Metadata = {
  title: 'Histori Laporan',
  description: 'Daftar laporan kejadian anonim yang masuk ke Gardu beserta statusnya, tanpa data pribadi.',
};

export default function LaporanHistoryPage() {
  return (
    <div className="container-x min-h-screen pb-24 pt-32">
      <Reveal>
        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">Transparansi</p>

        <h1 className="mt-3 font-display text-3xl font-bold tracking-tight text-white sm:text-5xl">Histori Laporan</h1>

        <p className="mt-3 max-w-2xl text-base leading-normal text-zinc-500">
          Pantau laporan kejadian yang masuk ke Gardu beserta statusnya. Hanya nomor, status, wilayah, jam kejadian, dan
          kategori yang ditampilkan.
        </p>
      </Reveal>

      <div className="mt-8">
        <ReportHistory />
      </div>

      <NewsSection />
    </div>
  );
}
