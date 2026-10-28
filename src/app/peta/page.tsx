import type { Metadata } from 'next';

import Reveal from '@/components/Reveal';
import RiskExplorer from '@/components/risk/RiskExplorer';

export const metadata: Metadata = {
  title: 'Peta Kerawanan',
  description: 'Lihat area dengan riwayat kejadian jalanan tercatat menurut periode jam di Yogyakarta.',
};

export default function PetaPage() {
  return (
    <div className="container-x min-h-screen pb-24 pt-32">
      <Reveal>
        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">Peta Kerawanan</p>

        <h1 className="mt-3 font-display text-3xl font-bold text-white sm:text-4xl">Area dengan riwayat kejadian tercatat.</h1>

        <p className="mt-2 max-w-2xl text-zinc-500">
          Skor 0-10 per area (±1 km) dihitung dari kejadian yang tercatat pada periode jam yang dipilih, dengan bobot yang
          lebih besar untuk kejadian terbaru. Gunakan sebagai panduan kewaspadaan, bukan jaminan keamanan.
        </p>
      </Reveal>

      <div className="mt-8">
        <RiskExplorer />
      </div>
    </div>
  );
}
