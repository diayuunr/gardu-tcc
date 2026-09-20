import { LEVEL_STYLE, RiskLevel } from '@/lib/types';

export default function RiskBadge({ level, score }: { level: RiskLevel; score?: number }) {
  const s = LEVEL_STYLE[level];
  return (
    <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ring-1 ${s.bg} ${s.text} ${s.ring}`}>
      <span className="relative flex h-2 w-2">
        {level === 'rawan' && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-70" />
        )}
        <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: s.hex }} />
      </span>
      {s.label}
      {typeof score === 'number' && <span className="opacity-70">- {score.toFixed(0)}</span>}
    </span>
  );
}