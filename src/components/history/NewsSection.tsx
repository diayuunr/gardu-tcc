import { ArrowRight, ArrowUpRight } from 'react-feather';

import NewsImage from '@/components/history/NewsImage';
import Reveal from '@/components/Reveal';
import { NEWS_ITEMS } from '@/lib/news';

/** Berita terkait: foto sampul (ilustrasi/arsip) + ringkasan netral + tautan ke sumber asli. */
export default function NewsSection() {
  return (
    <section className="mt-20" aria-labelledby="berita-terkait">
      <Reveal>
        <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-6">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.3em] text-emerald-400">News &amp; Updates</p>
            <h2 id="berita-terkait" className="mt-3 font-display text-3xl font-bold tracking-tight text-white sm:text-4xl">
              Berita Terkini
            </h2>
            <p className="mt-3 max-w-xl text-sm leading-relaxed text-zinc-500">
              Ikuti perkembangan informasi mengenai klitih dan kejahatan jalanan di Yogyakarta dan sekitarnya. Ringkasan
              ditulis netral oleh tim Gardu; baca selengkapnya di sumber.
            </p>
          </div>

          <a
            href="https://www.detik.com/tag/klitih"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-xs font-semibold text-emerald-300 transition hover:text-emerald-200"
          >
            Jelajahi berita lainnya
            <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
            <span className="sr-only">(situs eksternal)</span>
          </a>
        </div>
      </Reveal>

      <ul className="mt-7 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
        {NEWS_ITEMS.map((item, index) => (
          <li key={item.url}>
            <Reveal delay={index * 0.08} className="h-full">
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="group flex h-full flex-col overflow-hidden rounded-2xl border border-line bg-ink/40 transition duration-300 hover:-translate-y-1 hover:border-emerald-400/30 hover:bg-ink/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/60"
              >
                <div className="relative aspect-[16/10] overflow-hidden bg-zinc-900">
                  <NewsImage src={item.image} alt={item.imageAlt} />

                  <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/75 via-black/10 to-transparent" />

                  <span className="absolute left-4 top-4 rounded-full border border-white/15 bg-black/50 px-3 py-1.5 text-[9px] font-semibold uppercase tracking-wider text-white backdrop-blur-md">
                    {item.category}
                  </span>

                  <span className="absolute bottom-3 left-4 text-[9px] text-white/70">{item.imageNote}</span>

                  <span
                    className="absolute bottom-3 right-4 flex h-8 w-8 items-center justify-center rounded-full border border-white/20 bg-black/40 text-white transition group-hover:border-emerald-300 group-hover:bg-emerald-400 group-hover:text-emerald-950"
                    aria-hidden="true"
                  >
                    <ArrowUpRight className="h-5 w-5" />
                  </span>
                </div>

                <div className="flex flex-1 flex-col p-5 sm:p-6">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-zinc-500">
                    <span className="font-semibold text-emerald-300">{item.source}</span>
                    <span className="text-zinc-700" aria-hidden="true">•</span>
                    <span>{item.date}</span>
                  </div>

                  <h3 className="mt-4 line-clamp-3 font-display text-lg font-semibold leading-snug text-white transition group-hover:text-emerald-200">
                    {item.title}
                  </h3>

                  <p className="mt-3 line-clamp-4 flex-1 text-xs leading-relaxed text-zinc-400">{item.excerpt}</p>

                  <div className="mt-6 flex items-center justify-between border-t border-white/[0.06] pt-4">
                    <span className="text-[10px] text-zinc-500">
                      Baca artikel lengkap
                      <span className="sr-only"> (situs eksternal)</span>
                    </span>
                    <span className="text-xs font-semibold text-emerald-300 transition group-hover:translate-x-1" aria-hidden="true">
                      <ArrowRight className="h-4 w-4" />
                    </span>
                  </div>
                </div>
              </a>
            </Reveal>
          </li>
        ))}
      </ul>

      <div className="mt-6 flex items-start gap-3 rounded-xl border border-line bg-ink/30 px-4 py-3">
        <span className="text-emerald-400" aria-hidden="true">ⓘ</span>
        <p className="mt-0.5 text-[11px] leading-relaxed text-zinc-500">
          Berita berasal dari media eksternal. Informasi dugaan tindak pidana harus dipahami berdasarkan keterangan dan proses
          penyelidikan resmi. GARDU tidak menyatakan seseorang bersalah berdasarkan pemberitaan semata. Foto pada kartu
          adalah ilustrasi/arsip dari media sumber, bukan dokumentasi kejadian yang diberitakan.
        </p>
      </div>
    </section>
  );
}
