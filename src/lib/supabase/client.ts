/**
 * Klien Supabase Auth untuk peramban. Dipakai HANYA untuk masuk/keluar moderator; seluruh data laporan lewat backend
 * (Bearer token). Hanya memakai anon/publishable key; token tidak pernah dicatat ke konsol.
 */

import { createBrowserClient } from '@supabase/ssr';
import type { SupabaseClient } from '@supabase/supabase-js';

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_KEY = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

/** False bila env belum diisi: panel menampilkan penjelasan, bukan mode tiruan. */
export const SUPABASE_CONFIGURED = Boolean(SUPABASE_URL && SUPABASE_KEY);

let client: SupabaseClient | null = null;

/** Hanya panggil dari efek/handler (sisi peramban). */
export function getSupabase(): SupabaseClient | null {
  if (!SUPABASE_CONFIGURED) return null;

  client ??= createBrowserClient(SUPABASE_URL!, SUPABASE_KEY!);

  return client;
}
