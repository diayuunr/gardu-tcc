import type { Metadata } from 'next';

import ModerationPanel from '@/components/admin/ModerationPanel';
import Reveal from '@/components/Reveal';

export const metadata: Metadata = {
  title: 'Panel Moderator',
  description: 'Halaman khusus tim moderator Gardu.',
  robots: { index: false, follow: false },
};

export default function AdminPage() {
  return (
    <div className="container-x min-h-screen pb-24 pt-32">
      <Reveal>
        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">Moderator</p>

        <h1 className="mt-3 font-display text-3xl font-bold tracking-tight text-white sm:text-5xl">Panel Moderasi</h1>

        <p className="mt-3 max-w-2xl text-base leading-normal text-zinc-500">
          Tinjau laporan yang ditandai sistem atau menunggu verifikasi, lalu setujui, tolak, atau kembalikan ke antrean.
        </p>
      </Reveal>

      <div className="mt-8">
        <ModerationPanel />
      </div>
    </div>
  );
}
