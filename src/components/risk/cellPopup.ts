import { formatScore } from '@/lib/format';
import { LEVEL_HEX } from '@/lib/risk';
import type { BackendRiskLevel } from '@/lib/risk';
import { LEVEL_TITLE } from '@/lib/route';

function line(className: string, text: string): HTMLParagraphElement {
  const element = document.createElement('p');

  element.className = className;
  element.textContent = text; // bukan innerHTML: data server tidak pernah ditafsirkan sebagai HTML

  return element;
}

export interface CellInfo {
  label: string;
  level: BackendRiskLevel;
  score: number;
  count: number;
}

/** Isi popup sebuah sel: hanya agregat (tanpa koordinat insiden atau deskripsi). */
export function buildCellPopup(cell: CellInfo, bucketLabel: string): HTMLElement {
  const root = document.createElement('div');

  root.className = 'max-w-[230px] space-y-1.5';
  root.append(line('text-sm font-semibold text-white', cell.label));

  const level = document.createElement('p');
  const dot = document.createElement('span');

  level.className = 'flex items-center gap-2 text-xs font-medium text-zinc-200';
  dot.className = 'inline-block h-2.5 w-2.5 rounded-full';
  dot.style.background = LEVEL_HEX[cell.level];
  level.append(dot, `Tingkat ${LEVEL_TITLE[cell.level].toLowerCase()} · skor ${formatScore(cell.score)} dari 10`);
  root.append(level);

  root.append(
    line(
      'text-xs text-zinc-300',
      cell.count > 0
        ? `${cell.count} kejadian tercatat berkontribusi pada area ini`
        : 'Skor berasal dari kejadian tercatat di area sekitarnya.',
    ),
  );
  root.append(line('text-xs text-zinc-500', `Periode: ${bucketLabel}`));
  root.append(line('pt-1 text-[10px] text-zinc-500', 'Area sekitar ±1 km. Berdasarkan data tercatat, bukan jaminan keamanan.'));

  return root;
}
