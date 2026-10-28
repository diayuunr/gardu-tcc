import type { RouteSegment } from '@/lib/api-types';
import { formatMeters, formatScore } from '@/lib/format';
import { LEVEL_HEX } from '@/lib/risk';
import { LEVEL_TITLE, categoryLabel, describeIncidentHours, roadLabel } from '@/lib/route';

function line(className: string, text: string): HTMLParagraphElement {
  const element = document.createElement('p');

  element.className = className;
  element.textContent = text; // textContent (bukan innerHTML): data dari server tidak pernah ditafsirkan sebagai HTML

  return element;
}

/** Isi popup sebuah ruas. Hanya agregat per ruas (backend memang tidak mengirim data insiden individual). */
export function buildSegmentPopup(segment: RouteSegment): HTMLElement {
  const root = document.createElement('div');

  root.className = 'max-w-[240px] space-y-1.5';

  root.append(line('text-sm font-semibold text-white', roadLabel(segment)));

  if (segment.place_name) root.append(line('text-xs text-zinc-400', segment.place_name));

  const level = document.createElement('p');

  level.className = 'flex items-center gap-2 text-xs font-medium text-zinc-200';

  const dot = document.createElement('span');

  dot.className = 'inline-block h-2.5 w-2.5 rounded-full';
  dot.style.background = LEVEL_HEX[segment.risk_level];
  level.append(dot, `Tingkat ${LEVEL_TITLE[segment.risk_level].toLowerCase()} · skor ${formatScore(segment.risk_score)}`);
  root.append(level);

  root.append(line('text-xs text-zinc-400', `Panjang ruas ${formatMeters(segment.length_m)}`));

  if (segment.incident_count > 0) {
    root.append(line('text-xs text-zinc-300', `${segment.incident_count} kejadian tercatat di sekitar ruas`));

    const category = categoryLabel(segment.dominant_category);

    if (category) root.append(line('text-xs text-zinc-400', `Kategori terbanyak: ${category}`));

    const hours = describeIncidentHours(segment.incident_hours);

    if (hours) root.append(line('text-xs text-zinc-400', `Jam kejadian tercatat: ${hours}`));
  } else if (!segment.has_nearby_data) {
    root.append(line('text-xs text-amber-300', 'Belum ada data kejadian di sekitar ruas ini (bukan berarti aman).'));
  } else {
    root.append(line('text-xs text-zinc-400', 'Tidak ada kejadian tercatat di sekitar ruas pada jam ini.'));
  }

  root.append(line('pt-1 text-[10px] text-zinc-500', 'Berdasarkan data tercatat, bukan jaminan keamanan.'));

  return root;
}
