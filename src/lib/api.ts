/**
 * Klien HTTP bertipe untuk backend Gardu. Satu tempat untuk: URL dasar, batas waktu, pembatalan (AbortSignal),
 * dan penerjemahan error ke pesan Indonesia yang aman ditampilkan.
 *
 * PRIVASI: modul ini tidak pernah mencatat (console) permintaan, respons, koordinat, ataupun kata kunci;
 * pesan error hanya memuat `detail` dari backend (yang memang aman ditampilkan) atau teks tetap di bawah.
 */

import type { ApiErrorBody, ApiFieldError } from '@/lib/api-types';

// Tipe dan helper level/bucket tinggal di '@/lib/risk'; diekspor ulang agar impor lama tetap berjalan.
export {
  TIME_BUCKETS,
  currentTimeBucket,
  formatTimeBucket,
  toUiLevel,
} from '@/lib/risk';
export type { BackendRiskLevel, TimeBucket } from '@/lib/risk';

export const BACKEND_URL = (
  process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'
).replace(/\/$/, '');

export const DEFAULT_TIMEOUT_MS = 20_000;

export type ApiErrorKind =
  | 'validation' // 422
  | 'unauthorized' // 401
  | 'forbidden' // 403
  | 'not_found' // 404
  | 'conflict' // 409
  | 'rate_limit' // 429
  | 'unavailable' // 503
  | 'server' // 5xx lain / respons tak terduga
  | 'network' // peramban tak bisa menjangkau server
  | 'timeout' // melewati batas waktu
  | 'aborted'; // dibatalkan pemanggil (permintaan usang)

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  /** Kode HTTP, atau null bila tidak ada respons (jaringan/timeout/dibatalkan). */
  readonly status: number | null;
  /** Rincian per field dari 422 (maks 5 dari backend). */
  readonly fieldErrors: ApiFieldError[];

  constructor(
    kind: ApiErrorKind,
    message: string,
    status: number | null = null,
    fieldErrors: ApiFieldError[] = [],
  ) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

// ---------------------------------------------------------------------------
// Fungsi murni (diuji unit)
// ---------------------------------------------------------------------------

export function classifyStatus(status: number): ApiErrorKind {
  if (status === 401) return 'unauthorized';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 422 || status === 400) return 'validation';
  if (status === 429) return 'rate_limit';
  if (status === 503) return 'unavailable';
  return 'server';
}

const FALLBACK_MESSAGE: Record<ApiErrorKind, string> = {
  validation: 'Data yang dikirim belum sesuai. Periksa isian Anda lalu coba lagi.',
  unauthorized: 'Sesi Anda tidak valid atau sudah berakhir. Silakan masuk kembali.',
  forbidden: 'Anda tidak memiliki akses untuk tindakan ini.',
  not_found: 'Data yang diminta tidak ditemukan.',
  conflict: 'Permintaan bentrok dengan proses yang sedang berjalan. Coba lagi sebentar lagi.',
  rate_limit: 'Terlalu banyak permintaan. Tunggu sebentar lalu coba lagi.',
  unavailable: 'Layanan sedang tidak tersedia. Silakan coba lagi beberapa saat lagi.',
  server: 'Terjadi kesalahan pada server. Silakan coba lagi.',
  network:
    'Tidak dapat terhubung ke server. Periksa koneksi internet Anda lalu coba lagi.',
  timeout: 'Server terlalu lama merespons. Silakan coba lagi.',
  aborted: 'Permintaan dibatalkan.',
};

/** Pesan untuk pengguna: `detail` backend (bila string) untuk error HTTP, selain itu teks tetap per jenis. */
export function messageFor(kind: ApiErrorKind, detail?: unknown): string {
  const backendOwnsMessage =
    kind !== 'network' && kind !== 'timeout' && kind !== 'aborted';

  if (backendOwnsMessage && typeof detail === 'string' && detail.trim()) {
    return detail.trim();
  }

  return FALLBACK_MESSAGE[kind];
}

export function buildUrl(
  path: string,
  query?: Record<string, string | number | boolean | null | undefined>,
): string {
  const url = `${BACKEND_URL}${path.startsWith('/') ? path : `/${path}`}`;

  if (!query) return url;

  const params = new URLSearchParams();

  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    params.set(key, String(value));
  }

  const text = params.toString();

  return text ? `${url}?${text}` : url;
}

export function isAbortError(error: unknown): boolean {
  return (
    (error instanceof ApiError && error.kind === 'aborted') ||
    (error instanceof DOMException && error.name === 'AbortError')
  );
}

/** Pesan siap tampil dari error apa pun (ApiError, atau error tak terduga -> `fallback`). */
export function errorMessage(error: unknown, fallback = FALLBACK_MESSAGE.server): string {
  if (error instanceof ApiError) return error.message;

  return fallback;
}

// ---------------------------------------------------------------------------
// Permintaan
// ---------------------------------------------------------------------------

export interface RequestOptions {
  /** Batalkan permintaan usang (mis. saat pengguna mengetik lagi atau komponen dilepas). */
  signal?: AbortSignal;
  timeoutMs?: number;
  headers?: Record<string, string>;
  query?: Record<string, string | number | boolean | null | undefined>;
}

async function request<T>(
  method: 'GET' | 'POST' | 'PATCH',
  path: string,
  body: unknown,
  options: RequestOptions,
): Promise<T> {
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  let timedOut = false;

  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const external = options.signal;
  const onExternalAbort = () => controller.abort();

  if (external) {
    if (external.aborted) controller.abort();
    else external.addEventListener('abort', onExternalAbort, { once: true });
  }

  try {
    let response: Response;

    try {
      response = await fetch(buildUrl(path, options.query), {
        method,
        signal: controller.signal,
        headers: {
          Accept: 'application/json',
          ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
          ...options.headers,
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (error) {
      if (timedOut) {
        throw new ApiError('timeout', messageFor('timeout'));
      }

      if (controller.signal.aborted || (error instanceof DOMException && error.name === 'AbortError')) {
        throw new ApiError('aborted', messageFor('aborted'));
      }

      throw new ApiError('network', messageFor('network'));
    }

    if (!response.ok) {
      let parsed: ApiErrorBody | null = null;

      try {
        parsed = (await response.json()) as ApiErrorBody;
      } catch {
        // Bukan JSON (mis. halaman error proksi): pakai teks tetap.
      }

      const kind = classifyStatus(response.status);
      const fieldErrors = Array.isArray(parsed?.errors) ? parsed.errors : [];

      throw new ApiError(kind, messageFor(kind, parsed?.detail), response.status, fieldErrors);
    }

    try {
      return (await response.json()) as T;
    } catch {
      if (timedOut) throw new ApiError('timeout', messageFor('timeout'));
      if (controller.signal.aborted) throw new ApiError('aborted', messageFor('aborted'));

      throw new ApiError('server', messageFor('server'), response.status);
    }
  } finally {
    clearTimeout(timer);
    external?.removeEventListener('abort', onExternalAbort);
  }
}

const GET_RETRY_DELAY_MS = 400;

/** Gangguan sesaat yang wajar dicoba sekali lagi untuk permintaan baca: 502 dari backend (koneksi ke database terputus) atau jaringan putus. */
function isTransientFailure(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 502 || error.kind === 'network');
}

export async function apiGet<T>(path: string, options: RequestOptions = {}): Promise<T> {
  try {
    return await request<T>('GET', path, undefined, options);
  } catch (error) {
    // Hanya GET (aman diulang). Tidak mengulang bila dibatalkan/timeout/validasi/429/503.
    if (!isTransientFailure(error) || options.signal?.aborted) throw error;

    await new Promise((resolve) => setTimeout(resolve, GET_RETRY_DELAY_MS));

    if (options.signal?.aborted) throw error;

    return request<T>('GET', path, undefined, options);
  }
}

export function apiPost<T>(
  path: string,
  body: unknown,
  options: RequestOptions = {},
): Promise<T> {
  return request<T>('POST', path, body, options);
}

export function apiPatch<T>(
  path: string,
  body: unknown,
  options: RequestOptions = {},
): Promise<T> {
  return request<T>('PATCH', path, body, options);
}

/** Header Authorization untuk endpoint moderasi. */
export function bearer(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}
