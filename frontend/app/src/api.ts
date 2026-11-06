import { getSupabaseClient } from './supabase'
import type { Session } from '@supabase/supabase-js'

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1').replace(/\/$/, '')

export type ApiEnvelope<T> = { data: T; request_id?: string }
export type CollectionEnvelope<T> = { data: T[]; meta?: { next_cursor: string | null; has_more: boolean }; request_id?: string }

export class ApiError extends Error {
  status: number
  code: string

  constructor(message: string, status: number, code: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

type SessionRead = {
  data: { session: Session | null }
  error: Error | null
}

let inFlightSessionRead: Promise<SessionRead> | null = null

function readSession() {
  if (!inFlightSessionRead) {
    inFlightSessionRead = getSupabaseClient().auth.getSession().finally(() => {
      inFlightSessionRead = null
    })
  }
  return inFlightSessionRead
}

async function request<T>(path: string, init: RequestInit = {}) {
  let sessionResult: SessionRead
  try {
    sessionResult = await readSession()
  } catch (error) {
    console.error('[reactant] auth_session_read_failed', { scope: 'auth', error: error instanceof Error ? error.message : 'unknown_error' })
    throw error
  }
  const { data: { session }, error } = sessionResult
  if (error) throw new Error(`Could not read the signed-in session: ${error.message}`)
  if (!session?.access_token) throw new ApiError('Your session has expired. Sign in again.', 401, 'unauthenticated')

  const requestStartedAt = performance.now()
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...init.headers,
    },
  })

  if (response.status === 204) return { data: undefined as T, headers: response.headers }

  const payload = await response.json().catch(() => null) as {
    data?: T
    request_id?: string
    error?: { code?: string; message?: string }
  } | null
  if (!response.ok) {
    console.warn('[reactant] api_request_failed', {
      scope: 'api',
      method: init.method ?? 'GET',
      path,
      status: response.status,
      request_id: response.headers.get('X-Request-ID') ?? payload?.request_id,
      duration_ms: Math.round(performance.now() - requestStartedAt),
    })
    throw new ApiError(
      payload?.error?.message ?? `Request failed with status ${response.status}.`,
      response.status,
      payload?.error?.code ?? 'request_failed',
    )
  }
  if (!payload || !('data' in payload)) {
    throw new ApiError('The server returned an invalid response.', response.status, 'invalid_response')
  }
  console.info('[reactant] api_request_completed', {
    scope: 'api',
    method: init.method ?? 'GET',
    path,
    status: response.status,
    request_id: response.headers.get('X-Request-ID') ?? payload.request_id,
    duration_ms: Math.round(performance.now() - requestStartedAt),
  })
  return { data: payload.data as T, headers: response.headers }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  return (await request<T>(path, init)).data
}

export async function apiRequestWithHeaders<T>(path: string, init?: RequestInit) {
  return request<T>(path, init)
}

export type Business = {
  id: string
  name: string
  currency: string
  timezone: string
  country?: string | null
  support_email?: string | null
  phone?: string | null
  website?: string | null
  return_policy?: string | null
  delivery_policy?: string | null
  role: 'owner' | 'admin' | 'staff' | 'read_only' | null
}

export type Integration = {
  id: string
  provider: 'woocommerce' | 'telegram' | 'paypal' | 'shopify' | 'whatsapp'
  category: string
  status: string
  connected_at: string | null
  last_success_at: string | null
  last_error: string | null
  granted_scopes: string[]
  sync_status: string
}

export type AgentConfig = {
  enabled: boolean
  status: string
  business_context: string
  tone: string
  handoff_rule: string
  permissions: {
    answer_product_questions: boolean
    share_product_images: boolean
    create_carts_and_orders: boolean
    create_paypal_checkout: boolean
  }
  approval_policy: {
    require_approval_for_checkout: boolean
    checkout_threshold_minor: number | null
    currency: string
    approver_member_ids: string[]
  }
}

export type OwnerMessage = {
  id: string
  thread_id: string
  sender_type: 'user' | 'agent'
  sender_id: string
  display_name: string
  kind: 'text' | 'clarification' | 'approval_request' | 'exception' | 'status_update' | 'summary'
  text: string
  approval_id: string | null
  created_at: string
  read_at: string | null
}

export type Approval = {
  id: string
  business_id: string
  action_type: string
  status: string
  impact: Record<string, unknown>
  expires_at: string | null
  decided_by: string | null
  decided_at: string | null
  decision_note: string | null
  created_at: string
}

export function businessPath(businessId: string, resourcePath: string) {
  return `/businesses/${encodeURIComponent(businessId)}${resourcePath}`
}

export function newIdempotencyKey() {
  return crypto.randomUUID()
}
