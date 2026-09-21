import Reveal from '@/components/Reveal';

interface Resource {
  category: 'Darurat' | 'Pengaduan' | 'Rehabilitasi' | 'Pemantau Independen';
  title: string;
  contact: string;
  description: string;
}

const RESOURCES: Resource[] = [
  {
    category: 'Darurat',
    title: 'Call Center Polri',
    contact: '110',
    description: 'Layanan darurat kepolisian 24 jam. Gunakan untuk kondisi yang mengancam keselamatan jiwa.',
  },
  {
    category: 'Darurat',
    title: 'PSC 112 DIY',
    contact: '112',
    description: 'Pusat panggilan darurat terpadu Daerah Istimewa Yogyakarta (kecelakaan, bencana, kedaruratan).',
  },
  {
    category: 'Pengaduan',
    title: 'Satpol PP DIY',
    contact: '(0274) 5021060',
    description: 'Pengaduan ketertiban & keamanan wilayah, termasuk kejahatan jalanan. Tersedia juga layanan aduan masyarakat via Geoportal DIY.',
  },
  {
    category: 'Pengaduan',
    title: 'Hotline KemenPPPA 129',
    contact: '129',
    description: 'Layanan pengaduan perlindungan perempuan & anak, relevan bila korban adalah anak/remaja.',
  },
  {
    category: 'Rehabilitasi',
    title: 'Dinas Sosial DIY',
    contact: '(0274) 514932',
    description: 'Koordinasi program rehabilitasi sosial, termasuk pendampingan remaja terlibat kejahatan jalanan.',
  },
  {
    category: 'Rehabilitasi',
    title: 'Balai Rehabilitasi Sosial Anak',
    contact: 'KemenSos RI',
    description: 'Layanan pembinaan & rehabilitasi sosial bagi anak yang terlibat tindak kekerasan/kejahatan.',
  },
  {
    category: 'Pemantau Independen',
    title: 'Jogja Police Watch (JPW)',
    contact: 'Kanal media sosial JPW',
    description: 'Lembaga pemantau independen yang rutin mencatat dan merilis data kasus kejahatan jalanan di DIY, rujukan seed data Gardu.',
  },
];

const CATEGORY_STYLE: Record<Resource['category'], string> = {
  Darurat: 'border-red-400/30 bg-red-400/10 text-red-300',
  Pengaduan: 'border-amber-400/30 bg-amber-400/10 text-amber-300',
  Rehabilitasi: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-300',
  'Pemantau Independen': 'border-sky-400/30 bg-sky-400/10 text-sky-300',
};

export default function SumberDayaPage() {
  return (
    <div className="container-x min-h-screen pb-24 pt-32">
      <Reveal>
        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">Resource & Support Directory</p>
        <h1 className="mt-3 font-display text-4xl font-bold text-white">Sumber Daya & Kontak.</h1>
        <p className="mt-2 max-w-2xl text-zinc-500">
          Akses cepat ke kontak resmi satgas kejahatan jalanan, layanan pengaduan, dan
          program rehabilitasi remaja. Gardu berorientasi pencegahan dan dukungan.
        </p>
      </Reveal>

      <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {RESOURCES.map((r, i) => (
          <Reveal key={r.title} delay={i * 0.06}>
            <div className="glass-card h-full p-6 transition-all duration-300 hover:-translate-y-1 hover:border-emerald-400/25">
              <span className={`inline-block rounded-full border px-3 py-1 text-[11px] font-semibold ${CATEGORY_STYLE[r.category]}`}>
                {r.category}
              </span>
              <h3 className="mt-4 font-display text-lg font-semibold text-white">{r.title}</h3>
              <p className="mt-1 font-mono text-sm font-semibold text-emerald-300">{r.contact}</p>
              <p className="mt-3 text-sm leading-relaxed text-zinc-500">{r.description}</p>
            </div>
          </Reveal>
        ))}
      </div>

      <Reveal delay={0.2}>
        <div className="mt-10 rounded-3xl border border-amber-400/20 bg-amber-400/5 p-6 text-sm leading-relaxed text-zinc-500">
          <span className="font-semibold text-amber-300">Catatan:</span> Prinsip Gardu tidak ada penamaan,
          pelacakan, atau tindakan main hakim sendiri terhadap terduga pelaku.
        </div>
      </Reveal>
    </div>
  );
}