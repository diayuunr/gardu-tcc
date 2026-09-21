import Link from 'next/link';
import Image from 'next/image';

export default function Footer() {
  return (
    <footer className="border-t border-line bg-panel/60">
      <div className="container-x py-12">
        <div className="flex flex-col gap-8 md:flex-row md:items-start md:justify-between">
          <div className="max-w-sm">
            <p className="font-display text-lg font-bold text-white">GARDU</p>
            <p className="mt-2 text-sm leading-relaxed text-zinc-500">
              Sistem Kesadaran Komunitas dan Rute Aman Warga terhadap Kejahatan Jalanan (Klitih) di Yogyakarta
            </p>
            <div className="mt-6 flex items-center gap-4">
              <Image
                src="/jack.png"
                alt="Dita"
                width={40}
                height={40}
                className="h-8 w-8 rounded-full object-fit-cover"
              />

              <Image
                src="/tcc.png"
                alt="Anggota tim"
                width={40}
                height={40}
                className="h-8 w-8 rounded-full object-fit-cover"
              />

              <Image
                src="/utm.png"
                alt="Anggota tim"
                width={40}
                height={40}
                className="h-8 w-8 rounded-full object-cover"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-10 text-sm">
            <div>
              <p className="mb-3 font-semibold text-zinc-300">Fitur</p>
              <ul className="space-y-2 text-zinc-500">
                <li><Link className="transition hover:text-emerald-300" href="/lapor">Lapor Kejadian</Link></li>
                <li><Link className="transition hover:text-emerald-300" href="/peta">Peta Kerawanan</Link></li>
                <li><Link className="transition hover:text-emerald-300" href="/rute">Cek Rute Aman</Link></li>
                <li><Link className="transition hover:text-emerald-300" href="/sumber-daya">Sumber Daya</Link></li>
              </ul>
            </div>
            <div>
              <p className="mb-3 font-semibold text-zinc-300">Pemantauan</p>
              <ul className="space-y-2 text-zinc-500">
                <li><Link className="transition hover:text-emerald-300" href="/admin">Histori Laporan</Link></li>
              </ul>
            </div>
          </div>
        </div>
        <div className="mt-10 border-t border-line pt-6 text-xs text-zinc-600">
          Prototype Trunodjoyo Creative Competition (TCC) 2026
        </div>
      </div>
    </footer>
  );
}