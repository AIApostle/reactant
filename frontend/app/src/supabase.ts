import { createClient, type SupabaseClient } from '@supabase/supabase-js'

let client: SupabaseClient | null = null
const defaultSupabaseUrl = 'https://cmxbfvkpufeznhxtqvog.supabase.co'
const defaultSupabaseAnonKey = 'sb_publishable_vSyC9DWLzmiJ82QxUV05sg_SO5MEC60'

function getSupabaseConfig() {
  return {
    url: import.meta.env.VITE_SUPABASE_URL || defaultSupabaseUrl,
    anonKey: import.meta.env.VITE_SUPABASE_ANON_KEY || defaultSupabaseAnonKey,
  }
}

export function logAuthEvent(
  event: string,
  details: Record<string, unknown> = {},
  level: 'info' | 'warn' | 'error' = 'info',
) {
  const payload = { scope: 'auth', event, ...details }
  console[level](`[reactant] ${event}`, payload)
}

export function isSupabaseConfigured() {
  const { url, anonKey } = getSupabaseConfig()
  return Boolean(url && anonKey)
}

export function getSupabaseClient() {
  const { url, anonKey } = getSupabaseConfig()
  if (!url || !anonKey) {
    throw new Error('Authentication is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.')
  }
  client ??= createClient(url, anonKey, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
  })
  return client
}
