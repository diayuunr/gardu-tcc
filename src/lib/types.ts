export type RiskLevel = 'aman' | 'waspada' | 'rawan';

export const LEVEL_STYLE: Record<
  RiskLevel,
  { label: string; text: string; bg: string; ring: string; hex: string }
> = {
  aman:    { label: 'Aman',    text: 'text-emerald-300', bg: 'bg-emerald-400/10', ring: 'ring-emerald-400/30', hex: '#34d399' },
  waspada: { label: 'Waspada', text: 'text-amber-300',   bg: 'bg-amber-400/10',   ring: 'ring-amber-400/30',   hex: '#fbbf24' },
  rawan:   { label: 'Rawan',   text: 'text-red-300',     bg: 'bg-red-400/10',     ring: 'ring-red-400/30',     hex: '#f87171' },
};

// Skor 0-10 dari backend; level sudah ditentukan backend.
export type RiskPoint = {
  area_name: string;
  lat: number;
  lng: number;
  score: number;
  level: RiskLevel;
};

export interface FlaggedArea {
  area_name: string;
  place_name: string | null;
  risk_score: number;
}

export interface RouteResult {
  status: RiskLevel;
  maxScore: number;
  avoid: FlaggedArea[];
  watch: FlaggedArea[];
  areasChecked: number;
  areasWithData: number;
  distanceKm: number;
  durationMinutes: number;
  originName: string | null;
  destinationName: string | null;
}

export interface Place { name: string; lat: number; lng: number; }
