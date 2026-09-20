// =============================================================
// Simulasi ringkas tiga AI Agent untuk functional prototype.
// Versi produksi: pindahkan ke Supabase Edge Functions / FastAPI
// (LangChain/LangGraph), lalu panggil lewat supabase.functions.
// =============================================================

export interface VerificationResult {
  incident_type: string;
  ai_summary: string;
  flagged_reason: string | null;
  embedding: number[] | null;
}

const TYPE_KEYWORDS: [string, string[]][] = [
  ['pembacokan', ['bacok', 'bacokan', 'samurai', 'celurit']],
  ['penodongan', ['nodong', 'todong', 'senjata', 'pisau', 'pistol']],
  ['pencurian dengan kekerasan', ['rampas', 'rebut', 'curas', 'dibawa kabur']],
  ['pencurian kendaraan', ['maling motor', 'curanmor', 'mencuri motor', 'menjambret']],
  ['kejar-kejaran', ['kejar', 'dikejar']],
  ['penyerangan kelompok', ['kelompok', 'geng', 'ramai-ramai', 'masa']],
];

// Demo: embedding deterministik. Produksi: API embedding -> pgvector
function fakeEmbedding(text: string): number[] {
  let seed = 0;
  for (let i = 0; i < text.length; i++) seed = (seed * 33 + text.charCodeAt(i)) % 100000;
  return Array.from({ length: 768 }, () => {
    seed = (seed * 9301 + 49297) % 233280;
    return (seed / 233280) * 2 - 1;
  });
}

export function simulateVerification(description: string): VerificationResult {
  const lower = description.toLowerCase();

  let incident_type = 'lainnya';
  for (const [type, keys] of TYPE_KEYWORDS) {
    if (keys.some((k) => lower.includes(k))) {
      incident_type = type;
      break;
    }
  }

  // Heuristik penanda potensi duplikat/hoaks (REQ-F-012)
  let flagged_reason: string | null = null;
  if (description.length < 30) {
    flagged_reason = 'Deskripsi terlalu pendek — butuh tinjauan moderator.';
  } else if (/https?:\/\//.test(lower)) {
    flagged_reason = 'Mengandung tautan — potensi tidak konsisten.';
  }

  const ai_summary =
    `AI mengidentifikasi indikasi "${incident_type}". Laporan masuk antrean ` +
    `klasterisasi embedding untuk dibandingkan dengan laporan lain di radius ` +
    `waktu & lokasi berdekatan.`;

  return { incident_type, ai_summary, flagged_reason, embedding: fakeEmbedding(description) };
}