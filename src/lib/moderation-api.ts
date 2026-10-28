/** Panggilan ke /moderation/* dengan Bearer token sesi Supabase saat ini (selalu diambil segar; auto-refresh oleh Supabase). */

import { ApiError, apiGet, apiPatch, bearer, messageFor } from '@/lib/api';
import type {
  ModerationDecisionBody,
  ModerationList,
  ModerationResult,
  ModerationTargetStatus,
  Moderator,
} from '@/lib/api-types';
import { type QueueFilter, QUEUE_PAGE_SIZE, filterToStatus } from '@/lib/moderation';
import { getSupabase } from '@/lib/supabase/client';

async function authHeaders(): Promise<Record<string, string>> {
  const supabase = getSupabase();
  const { data } = (await supabase?.auth.getSession()) ?? { data: { session: null } };
  const token = data.session?.access_token;

  if (!token) throw new ApiError('unauthorized', messageFor('unauthorized'), 401);

  return bearer(token);
}

export async function fetchModerator(signal?: AbortSignal): Promise<Moderator> {
  return apiGet<Moderator>('/moderation/me', { signal, headers: await authHeaders() });
}

export async function fetchQueue(filter: QueueFilter, page: number, signal?: AbortSignal): Promise<ModerationList> {
  return apiGet<ModerationList>('/moderation/reports', {
    signal,
    headers: await authHeaders(),
    query: { status: filterToStatus(filter), limit: QUEUE_PAGE_SIZE, offset: page * QUEUE_PAGE_SIZE },
  });
}

export async function decideReport(
  id: string,
  status: ModerationTargetStatus,
  signal?: AbortSignal,
): Promise<ModerationResult> {
  const body: ModerationDecisionBody = { status };

  return apiPatch<ModerationResult>(`/moderation/reports/${encodeURIComponent(id)}`, body, {
    signal,
    headers: await authHeaders(),
  });
}
