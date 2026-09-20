import Link from 'next/link';

export default function Footer() {
  return (
    <footer className="border-t border-line bg-panel/60">
      <div className="container-x py-12">
        <div className="flex flex-col gap-8 md:flex-row md:items-start md:justify-between">
          <div className="max-w-sm">
            <p className="font-display text-lg font-bold text-white">GARDU</p>
            <p className="mt-2 text-sm leading-relaxed text-zinc-500">
              Sistem Kesadaran Komunitas dan Rute Aman Warga terhadap Kejahatan
              Jalanan (Klitih) di Yogyakarta. Berorientasi pencegahan dan
              dukungan — bukan penghakiman.
            </p>
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
              <p className="mb-3 font-semibold text-zinc-300">Internal</p>
              <ul className="space-y-2 text-zinc-500">
                <li><Link className="transition hover:text-emerald-300" href="/admin">Panel Moderasi</Link></li>
              </ul>
            </div>
          </div>
        </div>
        <div className="mt-10 border-t border-line pt-6 text-xs text-zinc-600">
          Prototype Trunodjoyo Creative Competition (TCC) 2026 - Data bersifat
          simulasi & anonim; tidak ada identitas pribadi yang disimpan.
        </div>
      </div>
    </footer>
  );
}