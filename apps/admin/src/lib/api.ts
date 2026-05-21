const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '')

export const apiBaseUrl = configuredBaseUrl || '/api'

export function apiPath(path: string): string {
  return `${apiBaseUrl}${path.startsWith('/') ? path : `/${path}`}`
}

export type ProductSort =
  | 'latest_price'
  | '-latest_price'
  | 'title'
  | '-title'
  | 'shop'
  | '-shop'
  | 'last_seen_at'
  | '-last_seen_at'

export interface ProductShop {
  id: number
  source: string
  source_id: string
  name: string
}

export interface ProductLatestPrice {
  price: string | null
  currency: string
  unit_raw: string | null
  source_updated_at: string | null
  parsed_at: string
}

export interface ProductSearchItem {
  id: number
  source: string
  source_product_id: string | null
  title: string
  normalized_title: string
  description: string | null
  category_id: number | null
  category_raw: string | null
  unit_raw: string | null
  image_url: string | null
  source_updated_at: string | null
  last_seen_at: string
  shop: ProductShop
  latest_price: ProductLatestPrice | null
}

export interface ProductSearchResponse {
  items: ProductSearchItem[]
  limit: number
  offset: number
}

export interface ProductPriceSnapshot {
  id: number
  price: string | null
  currency: string
  unit_raw: string | null
  source_updated_at: string | null
  parsed_at: string
}

export interface ProductPriceHistoryResponse {
  product_id: number
  items: ProductPriceSnapshot[]
}

export interface CategoryTreeItem {
  id: number
  slug: string
  name: string
  parent_id: number | null
  product_count: number
  children: CategoryTreeItem[]
}

export interface CategoryTreeResponse {
  items: CategoryTreeItem[]
}

export interface ShopListItem {
  id: number
  source: string
  source_id: string
  name: string
  address: string | null
  scrape_status: string
  last_scraped_at: string | null
  next_scrape_at: string | null
}

export interface ShopListResponse {
  items: ShopListItem[]
}

export interface ProductSearchParams {
  q?: string
  categoryId?: number
  shopId?: number
  sort?: ProductSort
  limit?: number
  offset?: number
}

export interface ScrapeStatusCount {
  status: string
  count: number
}

export interface RecentScrapeRun {
  id: number
  source: string
  shop_id: number | null
  status: string
  started_at: string
  finished_at: string | null
  items_seen: number
  items_saved: number
  error: string | null
}

export interface ScrapeHealthResponse {
  status_counts: ScrapeStatusCount[]
  recent_runs: RecentScrapeRun[]
}

export interface ScrapeHealthParams {
  source?: string
  shopId?: number
  status?: string
  limit?: number
}

export interface ShopListParams {
  source?: string
  status?: string
}

async function fetchJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(apiPath(path), {
    headers: { Accept: 'application/json' },
    signal,
  })

  if (!response.ok) {
    throw new Error(`API request failed with ${response.status}`)
  }

  return response.json() as Promise<T>
}

function appendOptionalParam(params: URLSearchParams, key: string, value: string | number | undefined): void {
  if (value !== undefined && value !== '') {
    params.set(key, String(value))
  }
}

export function fetchProducts(
  filters: ProductSearchParams,
  signal?: AbortSignal,
): Promise<ProductSearchResponse> {
  const params = new URLSearchParams()
  appendOptionalParam(params, 'q', filters.q?.trim())
  appendOptionalParam(params, 'category_id', filters.categoryId)
  appendOptionalParam(params, 'shop', filters.shopId)
  appendOptionalParam(params, 'sort', filters.sort)
  appendOptionalParam(params, 'limit', filters.limit)
  appendOptionalParam(params, 'offset', filters.offset)

  return fetchJson<ProductSearchResponse>(`/products?${params.toString()}`, signal)
}

export function fetchCategories(signal?: AbortSignal): Promise<CategoryTreeResponse> {
  return fetchJson<CategoryTreeResponse>('/categories', signal)
}

export function fetchShops(
  filters: ShopListParams = {},
  signal?: AbortSignal,
): Promise<ShopListResponse> {
  const params = new URLSearchParams()
  appendOptionalParam(params, 'source', filters.source)
  appendOptionalParam(params, 'status', filters.status)
  const query = params.toString()

  return fetchJson<ShopListResponse>(query ? `/shops?${query}` : '/shops', signal)
}

export function fetchProductPriceHistory(
  productId: number,
  signal?: AbortSignal,
): Promise<ProductPriceHistoryResponse> {
  return fetchJson<ProductPriceHistoryResponse>(`/products/${productId}/prices`, signal)
}

export function fetchScrapeHealth(
  filters: ScrapeHealthParams = {},
  signal?: AbortSignal,
): Promise<ScrapeHealthResponse> {
  const params = new URLSearchParams()
  appendOptionalParam(params, 'source', filters.source)
  appendOptionalParam(params, 'shop', filters.shopId)
  appendOptionalParam(params, 'status', filters.status)
  appendOptionalParam(params, 'limit', filters.limit)
  const query = params.toString()

  return fetchJson<ScrapeHealthResponse>(query ? `/scrapes/health?${query}` : '/scrapes/health', signal)
}
