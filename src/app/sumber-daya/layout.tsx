import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Sumber Daya & Kontak Darurat',
  description: 'Kontak layanan darurat, pengaduan, dan pendampingan di Yogyakarta serta lembaga pemantau independen.',
};

export default function ResourcesLayout({ children }: { children: React.ReactNode }) {
  return children;
}
