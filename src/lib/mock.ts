import { RiskPoint, levelOf } from './types';
import { PLACES } from './gazetteer';

// Mode demo: dipakai otomatis bila env Supabase belum diisi.
const BASE: Record<string, { base: number; amp: number }> = {
  'Malioboro & Tugu':            { base: 38, amp: 28 },
  'Jalan Kaliurang (Sekip/UGM)': { base: 34, amp: 34 },
  'Ring Road Utara (Mlati)':     { base: 30, amp: 40 },
  'Ring Road Timur (Depok)':     { base: 28, amp: 42 },
  'Gamping & Ambarketawang':     { base: 26, amp: 44 },
  'Depok & Berbah':              { base: 28, amp: 40 },
  'Jalan Wonosari (Piyungan)':   { base: 24, amp: 42 },
  'Kotagede':                    { base: 26, amp: 40 },
  'Sleman Kota & Tempel':        { base: 22, amp: 44 },
  'Wates & Kulon Progo':         { base: 20, amp: 42 },
  'Bantul Kota':                 { base: 20, amp: 38 },
  'Kaliurang Utara (Kopeng)':    { base: 18, amp: 40 },
};

function nightFactor(h: number) {
  if (h <= 4) return 1.0;
  if (h <= 6) return 0.45;
  if (h >= 22) return 0.75;
  return 0;
}

// Deterministik supaya tidak berubah-ubah saat re-render
function jitter(name: string, h: number) {
  let x = 0;
  const s = name + h;
  for (let i = 0; i < s.length; i++) x = (x * 31 + s.charCodeAt(i)) % 997;
  return (x % 9) - 4;
}

export function mockScores(hour: number): RiskPoint[] {
  return PLACES.map((p) => {
    const b = BASE[p.name] ?? { base: 20, amp: 35 };
    const score = Math.min(100, Math.max(5, b.base + b.amp * nightFactor(hour) + jitter(p.name, hour)));
    return {
      area_name: p.name, lat: p.lat, lng: p.lng,
      hour_of_day: hour, score, level: levelOf(score),
    };
  });
}