const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '')

export const apiBaseUrl = configuredBaseUrl || '/api'

export function apiPath(path: string): string {
  return `${apiBaseUrl}${path.startsWith('/') ? path : `/${path}`}`
}
