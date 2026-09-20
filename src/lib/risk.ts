import { supabase, isMockMode } from '@/lib/supabase';
import { mockScores } from './mock';
import { RiskPoint, RouteResult, levelOf, Place } from './types';

// Ambil skor kerawanan untuk jam tertentu (Supabase -> fallback mock)
export async function getRiskScores(hour: number): Promise<RiskPoint[]> {
  if (isMockMode || !supabase) {
    return mockScores(hour);
  }

  const { data, error } = await supabase
    .from('risk_scores')
    .select('area_name, center, hour_of_day, score')
    .eq('hour_of_day', hour);

  if (error || !data || data.length === 0) {
    return mockScores(hour);
  }

  return data.map((row) => {
    const pt = row.center as
      | { x: number; y: number }
      | string
      | null;

    let lng = 0;
    let lat = 0;

    if (typeof pt === 'string') {
      const [x, y] = pt.replace(/[()]/g, '').split(',');

      lng = parseFloat(x);
      lat = parseFloat(y);
    } else if (pt) {
      lng = pt.x;
      lat = pt.y;
    }

    const score = Number(row.score);

    return {
      area_name: row.area_name,
      lat,
      lng,
      hour_of_day: row.hour_of_day,
      score,
      level: levelOf(score),
    };
  });
}

// Safe Route Advisor: sampling titik di sepanjang garis asal-tujuan
export function checkRoute(
  origin: Place,
  dest: Place,
  hour: number,
  scores: RiskPoint[],
): RouteResult {
  const samples = 24;
  const found = new Map<string, number>();

  for (let i = 0; i < samples; i++) {
    const t = i / (samples - 1);

    const lat = origin.lat + (dest.lat - origin.lat) * t;
    const lng = origin.lng + (dest.lng - origin.lng) * t;

    for (const s of scores) {
      if (
        Math.abs(s.lat - lat) < 0.008 &&
        Math.abs(s.lng - lng) < 0.008
      ) {
        found.set(
          s.area_name,
          Math.max(found.get(s.area_name) ?? 0, s.score),
        );
      }
    }
  }

  const hotspots = [...found.entries()]
    .map(([name, score]) => ({
      name,
      score,
    }))
    .filter((h) => h.score >= 60)
    .sort((a, b) => b.score - a.score);

  const maxScore =
    hotspots.length > 0 ? hotspots[0].score : 0;

  return {
    status: levelOf(maxScore),
    maxScore,
    hotspots,
    checkedSamples: samples,
  };
}