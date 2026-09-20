export type RiskLevel = 'aman' | 'waspada' | 'rawan';
export type ReportStatus = 'menunggu_verifikasi' | 'terverifikasi' | 'duplikat' | 'hoaks';

export function levelOf(score: number): RiskLevel {
  if (score < 40) return 'aman';
  if (score < 70) return 'waspada';
  return 'rawan';
}

export const LEVEL_STYLE: Record<
  RiskLevel,
  { label: string; text: string; bg: string; ring: string; hex: string }
> = {
  aman:    { label: 'Aman',    text: 'text-emerald-300', bg: 'bg-emerald-400/10', ring: 'ring-emerald-400/30', hex: '#34d399' },
  waspada: { label: 'Waspada', text: 'text-amber-300',   bg: 'bg-amber-400/10',   ring: 'ring-amber-400/30',   hex: '#fbbf24' },
  rawan:   { label: 'Rawan',   text: 'text-red-300',     bg: 'bg-red-400/10',     ring: 'ring-red-400/30',     hex: '#f87171' },
};

export type RiskPoint = {
  area_name: string;
  lat: number;
  lng: number;
  score: number;
  level: 'aman' | 'waspada' | 'rawan';
};

export interface Report {
  id: string;
  description: string;
  location_text: string;
  occurred_at: string;
  incident_type?: string | null;
  status: ReportStatus;
  ai_summary?: string | null;
  flagged_reason?: string | null;
  created_at?: string;
}

export interface Hotspot { name: string; score: number; }

export interface RouteResult {
  status: RiskLevel;
  maxScore: number;
  hotspots: Hotspot[];
  checkedSamples: number;
}

export interface Place { name: string; lat: number; lng: number; }