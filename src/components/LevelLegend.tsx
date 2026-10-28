import { LEVEL_HEX, LEVEL_RANGES, MAX_RISK_SCORE, RISK_THRESHOLDS } from '@/lib/risk';

const STOP_SEDANG = (RISK_THRESHOLDS.sedang / MAX_RISK_SCORE) * 100;
const STOP_TINGGI = (RISK_THRESHOLDS.tinggi / MAX_RISK_SCORE) * 100;

/** Pita warna 0-10 dengan batas tegas di ambang backend (sedang >= 3, tinggi >= 7). */
const BAR_GRADIENT = `linear-gradient(to right, ${LEVEL_HEX.rendah} 0%, ${LEVEL_HEX.rendah} ${STOP_SEDANG}%, ${LEVEL_HEX.sedang} ${STOP_SEDANG}%, ${LEVEL_HEX.sedang} ${STOP_TINGGI}%, ${LEVEL_HEX.tinggi} ${STOP_TINGGI}%, ${LEVEL_HEX.tinggi} 100%)`;

/**
 * Legenda skala risiko 0-10 dengan ambang yang sama dengan backend (lihat `RISK_THRESHOLDS`).
 * `list` = daftar bertanda warna; `bar` = pita skala dengan ambang berlabel.
 */
export default function LevelLegend({
  variant = 'list',
  showNote = true,
  className = '',
}: {
  variant?: 'list' | 'bar';
  showNote?: boolean;
  className?: string;
}) {
  return (
    <div className={className}>
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">
        Skala kerawanan (0-10)
      </p>

      {variant === 'bar' ? (
        <div className="mt-3">
          <div
            className="h-2.5 w-full rounded-full"
            style={{ background: BAR_GRADIENT }}
            role="img"
            aria-label={LEVEL_RANGES.map((r) => `${r.title} ${r.range}`).join(', ')}
          />

          <div className="relative mt-1.5 h-4 text-[11px] text-zinc-500" aria-hidden="true">
            <span className="absolute left-0">0</span>
            <span className="absolute -translate-x-1/2" style={{ left: `${STOP_SEDANG}%` }}>
              {RISK_THRESHOLDS.sedang}
            </span>
            <span className="absolute -translate-x-1/2" style={{ left: `${STOP_TINGGI}%` }}>
              {RISK_THRESHOLDS.tinggi}
            </span>
            <span className="absolute right-0">{MAX_RISK_SCORE}</span>
          </div>

          <div className="mt-1 grid grid-cols-3 gap-2 text-xs">
            {LEVEL_RANGES.map((r) => (
              <span key={r.level} className="text-zinc-400">
                <span className="font-semibold" style={{ color: LEVEL_HEX[r.level] }}>
                  {r.title}
                </span>{' '}
                {r.range}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <ul className="mt-3 space-y-2">
          {LEVEL_RANGES.map((r) => (
            <li key={r.level} className="flex items-center gap-3 text-sm">
              <span
                className="h-3 w-3 shrink-0 rounded-full"
                style={{ background: LEVEL_HEX[r.level] }}
                aria-hidden="true"
              />
              <span className="font-medium text-zinc-200">{r.title}</span>
              <span className="text-zinc-500">skor {r.range}</span>
            </li>
          ))}
        </ul>
      )}

      {showNote && (
        <p className="mt-3 text-xs leading-relaxed text-zinc-500">
          Berdasarkan data kejadian yang tercatat. Skor rendah bukan jaminan aman.
        </p>
      )}
    </div>
  );
}
