import { createClient, SupabaseClient } from '@supabase/supabase-js';

const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? '';
const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? '';

// Mode demo: jalan tanpa backend pakai data mock
export const isMockMode = !url || !anon;

export const supabase: SupabaseClient | null = isMockMode
  ? null
  : createClient(url, anon);