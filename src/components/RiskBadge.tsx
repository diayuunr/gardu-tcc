import { formatScore } from '@/lib/format';
import { AnyLevel, LEVEL_STYLE, normalizeLevel } from '@/lib/risk';

const SIZE_CLASS = {
  sm: 'px-2.5 py-0.5 text-[11px]',
  md: 'px-3 py-1 text-xs',
  lg: 'px-4 py-1.5 text-sm',
} as const;

/**
 * Lencana tingkat kerawanan. Menerima kosakata level apa pun (rendah/sedang/tinggi, aman/waspada/rawan, atau status
 * rute berisiko_tinggi); `label` menggantikan teks bawaan (mis. "Perlu waspada" untuk status rute).
 */
export default function RiskBadge({
  level,
  score,
  label,
  size = 'md',
  className = '',
}: {
  level: AnyLevel;
  score?: number;
  label?: string;
  size?: keyof typeof SIZE_CLASS;
  className?: string;
}) {
  const ui = normalizeLevel(level);
  const style = LEVEL_STYLE[ui];

  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full font-semibold ring-1 ${SIZE_CLASS[size]} ${style.bg} ${style.text} ${style.ring} ${className}`}
    >
      <span className="relative flex h-2 w-2" aria-hidden="true">
        {ui === 'rawan' && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-70 motion-reduce:animate-none" />
        )}
        <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: style.hex }} />
      </span>
      <span className="sr-only">Tingkat kerawanan: </span>
      {label ?? style.label}
      {typeof score === 'number' && Number.isFinite(score) && (
        <span className="opacity-70">
          <span aria-hidden="true">- {formatScore(score)}</span>
          <span className="sr-only">, skor {formatScore(score)} dari 10</span>
        </span>
      )}
    </span>
  );
}
