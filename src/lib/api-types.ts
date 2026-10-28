/**
 * Tipe respons/permintaan backend. Sumber: backend/docs/API.md dan backend/docs/examples/route_check_example.json
 * (dilengkapi skema Pydantic backend untuk /risk/heatmap, /risk/score dan /risk/summary, yang di API.md baru
 * dijelaskan bagian nama wilayahnya saja).
 */

import type { BackendRiskLevel, RouteStatus, TimeBucket } from '@/lib/risk';

// ---------------------------------------------------------------------------
// Error
// ---------------------------------------------------------------------------

export interface ApiFieldError {
  field: string;
  message: string;
}

/** Bentuk error backend: `detail` selalu string; 422 validasi menambah `errors`. */
export interface ApiErrorBody {
  detail?: unknown;
  errors?: ApiFieldError[];
}

// ---------------------------------------------------------------------------
// Wilayah dan laporan
// ---------------------------------------------------------------------------

export type AreaLevel = 'kabkota' | 'kecamatan' | 'kelurahan';

/** GET /areas */
export interface Area {
  kode: string;
  nama: string;
  tingkat: AreaLevel;
  parent_kode: string | null;
  latitude: number | null;
  longitude: number | null;
}

export interface AreaList {
  count: number;
  areas: Area[];
}

export type ReportApiStatus =
  | 'menunggu_verifikasi'
  | 'terverifikasi'
  | 'ditandai_duplikat'
  | 'ditandai_hoaks';

/** Kategori jenis kejadian (kosakata tetap backend; dipakai `incident_type_hint`, `jenis`, `dominant_category`). */
export const INCIDENT_CATEGORIES = [
  'klitih',
  'penyerangan',
  'bentrok antar kelompok',
  'begal/penodongan',
  'kejadian mencurigakan',
  'pengrusakan',
  'lainnya',
] as const;

export type IncidentCategory = (typeof INCIDENT_CATEGORIES)[number];

/** Body POST /reports (jalur berjenjang). */
export interface ReportCreateBody {
  description: string;
  occurred_at: string;
  kabkota_kode: string;
  kecamatan_kode: string;
  kelurahan_kode?: string;
  jalan?: string;
  latitude?: number;
  longitude?: number;
  incident_type_hint?: IncidentCategory;
}

/** Respons 201 POST /reports. */
export interface ReportCreated {
  id: string;
  status: ReportApiStatus;
  created_at: string;
}

/** GET /reports/public: hanya field anonim. */
export interface PublicReport {
  nomor: string;
  status: 'menunggu_verifikasi' | 'terverifikasi';
  occurred_at: string;
  wilayah: string;
  jenis: IncidentCategory;
}

export interface PublicReportList {
  total: number;
  limit: number;
  offset: number;
  items: PublicReport[];
}

/** GET /reports/stats */
export interface ReportStats {
  total_reports: number;
  reports_by_status: Record<ReportApiStatus, number>;
  verified_incidents: number;
  verified_incidents_from_reports: number;
  historical_incidents: number;
}

// ---------------------------------------------------------------------------
// Pencarian tempat
// ---------------------------------------------------------------------------

export type PlaceSource = 'landmark' | 'photon' | 'nominatim' | 'wilayah' | 'mapbox';

/** Satu hasil GET /geo/search. */
export interface PlaceHit {
  label: string;
  place_name: string;
  latitude: number;
  longitude: number;
  source: PlaceSource;
  category: string | null;
}

export interface PlaceSearch {
  count: number;
  results: PlaceHit[];
  /** true: ada layanan pencarian yang gagal sehingga hasil mungkin kurang lengkap (bukan error). */
  degraded: boolean;
}

/** GET /geo/reverse */
export interface ReverseGeocode {
  label: string;
  kecamatan_kode: string | null;
  in_diy: boolean;
}

// ---------------------------------------------------------------------------
// Risiko (peta)
// ---------------------------------------------------------------------------

/** GET /risk/score */
export interface RiskScore {
  area_name: string;
  place_name: string | null;
  label: string;
  time_bucket: TimeBucket;
  risk_score: number;
  risk_level: BackendRiskLevel;
  contributing_incident_count: number;
  has_data: boolean;
  narrative: string | null;
}

/** Satu sel di GET /risk/heatmap. */
export interface RiskCell {
  area_name: string;
  place_name: string | null;
  label: string;
  latitude: number;
  longitude: number;
  risk_score: number;
  risk_level: BackendRiskLevel;
  contributing_incident_count: number;
}

export interface RiskHeatmap {
  time_bucket: TimeBucket;
  cells: RiskCell[];
  updated_at: string | null;
}

export interface RegionRisk {
  kecamatan_kode: string;
  place_name: string;
  label: string;
  risk_score: number;
  risk_level: BackendRiskLevel;
  cell_count: number;
  incident_count: number;
}

/** GET /risk/summary */
export interface RiskSummary {
  time_bucket: TimeBucket;
  regions: RegionRisk[];
  unassigned_cell_count: number;
  updated_at: string | null;
}

// ---------------------------------------------------------------------------
// Cek rute
// ---------------------------------------------------------------------------

/** Titik rute: koordinat (disarankan) ATAU teks. */
export type RoutePlaceInput =
  | { latitude: number; longitude: number }
  | { text: string };

export interface RouteCheckBody {
  origin: RoutePlaceInput;
  destination: RoutePlaceInput;
  /** ISO 8601; tanpa zona waktu dianggap WIB oleh backend. */
  departure_time?: string;
}

/** GeoJSON LineString; koordinat berurutan [bujur, lintang]. */
export interface GeoLineString {
  type: 'LineString';
  coordinates: [number, number][];
}

export interface RouteSegment {
  index: number;
  road_name: string;
  place_name: string | null;
  start_km: number;
  end_km: number;
  length_m: number;
  risk_level: BackendRiskLevel;
  risk_score: number;
  incident_count: number;
  dominant_category: IncidentCategory | null;
  /** Bucket jam kejadian historis -> jumlah. */
  incident_hours: Partial<Record<TimeBucket, number>>;
  has_nearby_data: boolean;
  peak_time_bucket: TimeBucket;
  geometry: GeoLineString;
}

export interface RouteSummary {
  status: RouteStatus;
  max_risk_score: number;
  distance_km: number;
  duration_minutes: number;
  data_coverage: number;
  data_limited: boolean;
  high_exposure_m: number;
  medium_exposure_m: number;
  incident_count: number;
  time_buckets: TimeBucket[];
}

/** Ruas berlevel tinggi/sedang (kompatibilitas lama: areas_to_avoid / areas_to_watch). */
export interface RouteFlaggedArea {
  area_name: string;
  place_name: string | null;
  label: string;
  latitude: number;
  longitude: number;
  time_bucket: TimeBucket;
  risk_score: number;
  risk_level: BackendRiskLevel;
  segment_index: number;
}

export interface RoutePointInfo {
  latitude: number;
  longitude: number;
  place_name: string;
}

export interface RouteAlternative {
  risk_level: RouteStatus;
  max_risk_score: number;
  distance_km: number;
  duration_minutes: number;
  data_coverage: number;
  data_limited: boolean;
  is_lowest_risk: boolean;
  /** Selisih menit vs rute utama; negatif = lebih cepat. */
  extra_minutes: number;
  summary: RouteSummary;
  geometry: GeoLineString;
  segments: RouteSegment[];
  reasons: string[];
}

/** Respons POST /route/check. */
export interface RouteCheck {
  risk_level: RouteStatus;
  max_risk_score: number;
  areas_to_avoid: RouteFlaggedArea[];
  areas_to_watch: RouteFlaggedArea[];
  areas_checked: number;
  areas_with_data: number;
  origin: RoutePointInfo;
  destination: RoutePointInfo;
  distance_km: number;
  duration_minutes: number;
  departure_time: string;
  time_buckets: TimeBucket[];
  data_coverage: number;
  data_limited: boolean;
  data_note: string | null;
  location_notes: string[];
  alternatives: RouteAlternative[];
  safer_alternative_available: boolean;
  summary: RouteSummary;
  geometry: GeoLineString;
  segments: RouteSegment[];
  reasons: string[];
  /** 0 = rute utama; i >= 1 = alternatif ke-i (1-based). */
  recommended_route: number;
  narrative: string | null;
}

// ---------------------------------------------------------------------------
// Moderasi (butuh Authorization: Bearer <token Supabase Auth>)
// ---------------------------------------------------------------------------

export interface Moderator {
  display_name: string;
}

export interface ModerationReport {
  id: string;
  nomor: string;
  status: ReportApiStatus;
  flagged_reason: string | null;
  moderation_decision: 'disetujui' | 'ditolak' | null;
  description: string;
  location_text: string;
  occurred_at: string;
  created_at: string;
  extracted_incident_type: string | null;
  incident_type_hint: IncidentCategory | null;
  incident_id: string | null;
}

export interface ModerationList {
  total: number;
  limit: number;
  offset: number;
  items: ModerationReport[];
}

export type ModerationTargetStatus =
  | 'terverifikasi'
  | 'ditandai_hoaks'
  | 'menunggu_verifikasi';

export interface ModerationDecisionBody {
  status: ModerationTargetStatus;
}

export interface ModerationResult {
  id: string;
  status: ReportApiStatus;
  changed: boolean;
  incident_status: 'baru' | 'terverifikasi' | null;
  scores_refresh_scheduled: boolean;
}
