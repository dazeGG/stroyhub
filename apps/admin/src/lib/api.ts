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
  price_kind: string
  price_text: string | null
  currency: string
  unit_raw: string | null
  source_updated_at: string | null
  parsed_at: string
}

export interface ProductCategoryOverride {
  id: number
  category_id: number
  previous_category_id: number | null
  reason: string | null
  status: string
  created_by: string | null
  created_at: string
  updated_by: string | null
  updated_at: string
  deactivated_by: string | null
  deactivated_at: string | null
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
  category_override: ProductCategoryOverride | null
}

export interface ProductSearchResponse {
  items: ProductSearchItem[]
  limit: number
  offset: number
  total: number
}

export type ProductNormalizationState =
  | 'ineligible'
  | 'needs_review'
  | 'eligible_unmatched'
  | 'candidate_match'
  | 'accepted'

export interface ProductNormalizationEligibility {
  status: string
  confidence: string | null
  score: number | null
  reasons: string[]
}

export interface ProductNormalizationMatchSummary {
  accepted_match_id: number | null
  accepted_canonical_product_id: number | null
  accepted_canonical_title: string | null
  candidate_count: number
  rejected_count: number
}

export interface ProductNormalizationCandidateMatch {
  id: number
  canonical_product_id: number
  canonical_title: string
  canonical_normalized_title: string
  canonical_category_id: number | null
  confidence: string
  method: string
  reason: Record<string, unknown> | null
}

export interface ProductNormalizationQueueItem {
  id: number
  state: ProductNormalizationState
  source: string
  source_product_id: string | null
  title: string
  normalized_title: string
  category_id: number | null
  category_slug: string | null
  category_name: string | null
  category_raw: string | null
  unit_raw: string | null
  image_url: string | null
  last_seen_at: string
  is_not_product: boolean
  shop: ProductShop
  latest_price: ProductLatestPrice | null
  catalog_eligibility: ProductNormalizationEligibility | null
  match_summary: ProductNormalizationMatchSummary
  candidate_matches: ProductNormalizationCandidateMatch[]
}

export interface ProductNormalizationQueueResponse {
  items: ProductNormalizationQueueItem[]
  limit: number
  offset: number
  total: number
}

export type PatronReviewAction = 'product' | 'not_product' | 'skip'
export type PatronReviewMode = 'needs_review' | 'patron_rejected'

export interface PatronReviewParams {
  mode?: PatronReviewMode
  minProbability?: number
}

export interface PatronReviewCategory {
  id: number
  slug: string
  name: string
}

export interface PatronReviewItem {
  id: number
  source: string
  source_product_id: string | null
  title: string
  normalized_title: string
  description: string | null
  category_id: number | null
  category: PatronReviewCategory | null
  category_raw: string | null
  unit_raw: string | null
  image_url: string | null
  source_updated_at: string | null
  last_seen_at: string
  is_not_product: boolean
  shop: ProductShop
  latest_price: ProductLatestPrice | null
  catalog_eligibility: Record<string, unknown> | null
  raw: Record<string, unknown> | null
}

export interface PatronReviewStats {
  total: number
  remaining: number
  reviewed: number
  skipped: number
}

export interface PatronReviewPageResponse {
  item: PatronReviewItem | null
  stats: PatronReviewStats
}

export interface PatronReviewDecisionResponse {
  action: PatronReviewAction | 'undo'
  product_id: number | null
  stats: PatronReviewStats
}

export type CatalogWorkflowQueueName =
  | 'auto_acceptable'
  | 'review_needed'
  | 'data_problems'
  | 'possible_duplicates'
  | 'normalized_items'

export interface CatalogWorkflowDashboardCount {
  queue: CatalogWorkflowQueueName
  count: number
}

export interface CatalogWorkflowDashboardResponse {
  counts: CatalogWorkflowDashboardCount[]
}

export interface CatalogWorkflowCategory {
  id: number
  slug: string
  name: string
}

export interface CatalogWorkflowReason {
  stage: string
  status: string | null
  action: string | null
  reasons: string[]
  blockers: string[]
  message: string | null
}

export interface CatalogWorkflowQueueItem {
  id: number
  queue: CatalogWorkflowQueueName
  source: string
  source_product_id: string | null
  title: string
  normalized_title: string
  category_id: number | null
  category: CatalogWorkflowCategory | null
  category_raw: string | null
  unit_raw: string | null
  image_url: string | null
  last_seen_at: string
  is_not_product: boolean
  shop: ProductShop
  latest_price: ProductLatestPrice | null
  catalog_quality: Record<string, unknown> | null
  reasons: CatalogWorkflowReason[]
  match_summary: ProductNormalizationMatchSummary
  candidate_matches: ProductNormalizationCandidateMatch[]
}

export interface CatalogWorkflowQueueResponse {
  queue: CatalogWorkflowQueueName
  items: CatalogWorkflowQueueItem[]
  limit: number
  offset: number
  total: number
}

export interface CatalogWorkflowQueueParams {
  source?: string
  shopId?: number
  categoryId?: number
  q?: string
  limit?: number
  offset?: number
}

export interface CatalogWorkflowAutoAcceptRequest extends CatalogWorkflowQueueParams {
  dryRun?: boolean
  reason?: string
}

export interface CatalogWorkflowAutoAcceptItem {
  source_product_id: number
  title: string
  action: string | null
  status: 'would_accept' | 'accepted' | 'skipped'
  reason: string
  canonical_product_id: number | null
  match_id: number | null
}

export interface CatalogWorkflowAutoAcceptResponse {
  dry_run: boolean
  total: number
  page_size: number
  would_accept: number
  accepted: number
  skipped: number
  items: CatalogWorkflowAutoAcceptItem[]
}

export interface CanonicalProductListItem {
  id: number
  title: string
  normalized_title: string
  category_id: number | null
  category: {
    id: number
    slug: string
    name: string
  } | null
  brand: string | null
  model: string | null
  unit_raw: string | null
  attributes: Record<string, unknown> | null
  match_status: string
  created_at: string
  updated_at: string
  match_counts: {
    accepted: number
    candidate: number
    rejected: number
  }
}

export interface CanonicalProductListResponse {
  items: CanonicalProductListItem[]
  limit: number
  offset: number
  total: number
}

export interface CanonicalSourceLatestPrice {
  price: string | null
  price_kind: string
  price_text: string | null
  currency: string
  unit_raw: string | null
  source_updated_at: string | null
  parsed_at: string
}

export interface CanonicalLinkedSourceProduct {
  id: number
  match_id: number
  source: string
  source_product_id: string | null
  title: string
  normalized_title: string
  shop_id: number
  shop_name: string
  shop_source_id: string
  category_raw: string | null
  unit_raw: string | null
  source_url: string | null
  image_url: string | null
  last_seen_at: string
  latest_price: CanonicalSourceLatestPrice | null
  confidence: string
}

export interface CanonicalOfferGroup {
  source: string
  shop_id: number
  shop_source_id: string
  shop_name: string
  items: CanonicalLinkedSourceProduct[]
}

export interface CanonicalProductDetail extends CanonicalProductListItem {
  accepted_source_products: CanonicalLinkedSourceProduct[]
  accepted_offer_groups: CanonicalOfferGroup[]
  candidate_source_products: CanonicalLinkedSourceProduct[]
  rejected_source_products: CanonicalLinkedSourceProduct[]
}

export interface CanonicalProductUpdatePayload {
  title?: string
  normalized_title?: string
  category_id?: number | null
  brand?: string | null
  model?: string | null
  unit_raw?: string | null
  attributes?: Record<string, unknown> | null
  match_status?: string
}

export interface ProductMatchDecision {
  id: number
  canonical_product_id: number
  source_product_id: number
  confidence: string
  status: string
  method: string
  matched_at: string
  reviewed_at: string | null
  reviewed_by: string | null
  reason: Record<string, unknown> | null
}

export type ProductMatchAutoAcceptMethod = 'exact_normalized_title' | 'exact_title'

export interface ProductMatchAutoAcceptRequest {
  source?: string
  shopId?: number
  categoryId?: number
  q?: string
  minConfidence?: number
  methods?: ProductMatchAutoAcceptMethod[]
  limit?: number
  dryRun?: boolean
  reason?: string
}

export interface ProductMatchAutoAcceptItem {
  match_id: number
  canonical_product_id: number
  canonical_title: string
  source_product_id: number
  source_title: string
  confidence: string
  method: string
}

export interface ProductMatchAutoAcceptResponse {
  dry_run: boolean
  candidates_seen: number
  would_accept: number
  accepted: number
  skipped_already_accepted: number
  skipped_ambiguous: number
  skipped_ineligible: number
  skipped_category_mismatch: number
  skipped_low_confidence: number
  skipped_method: number
  skipped_decision_review: number
  skipped_previously_rejected: number
  followup_candidates_created: number
  items: ProductMatchAutoAcceptItem[]
}

export interface ProductBulkNormalizationRequest {
  source?: string
  shopId?: number
  categoryId?: number
  q?: string
  limit?: number
  offset?: number
  dryRun?: boolean
  reason?: string
}

export interface ProductBulkNormalizationItem {
  source_product_id: number
  title: string
  normalized_title: string
  canonical_product_id: number | null
  match_id: number | null
}

export interface ProductBulkNormalizationResponse {
  dry_run: boolean
  total: number
  page_size: number
  would_create: number
  created: number
  skipped_became_candidate: number
  skipped_already_accepted: number
  skipped_ineligible: number
  skipped_needs_review: number
  followup_candidates_created: number
  items: ProductBulkNormalizationItem[]
}

export interface ProductDataProblemRequest {
  isNotProduct?: boolean
  reason?: string
}

export interface ProductPriceSnapshot {
  id: number
  price: string | null
  price_kind: string
  price_text: string | null
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
  shop_identity_id: number | null
  identity: ShopIdentitySummary | null
  source: string
  source_id: string
  source_type: SourceType
  name: string
  address: string | null
  url: string | null
  scrape_status: string
  last_scraped_at: string | null
  next_scrape_at: string | null
  scrape_interval: number
  error_count: number
  is_preferred_source: boolean
  twogis_large_catalog: TwogisLargeCatalogState | null
  enqueue_failed: EnqueueFailure | null
}

export interface ShopListResponse {
  items: ShopListItem[]
}

export interface ShopScrapeRetryResponse {
  shop_id: number
  source: string
  source_type: SourceType
  status: string
  task_id: string | null
  reason: string | null
}

export type SourceType = '2gis' | 'official_api' | 'official_html'

export type IdentityStatus = 'active' | 'hold' | 'disabled' | 'out_of_scope'

export interface ShopIdentitySummary {
  id: number
  display_name: string
  status: IdentityStatus
  preferred_source: string | null
}

export interface ShopIdentity {
  id: number
  display_name: string
  address: string | null
  website_url: string | null
  preferred_source: string | null
  status: IdentityStatus
  notes: string | null
  locked_fields: Record<string, unknown> | null
  source_count: number | null
}

export interface ShopIdentityListResponse {
  items: ShopIdentity[]
}

export interface TwogisLargeCatalogState {
  enabled: boolean
  threshold: number
  total: number | null
  page_size: number
  pages_per_run: number
  next_page: number
  items_loaded: number
  completed: boolean
  last_stop_reason: string | null
}

export interface EnqueueFailure {
  operation: string
  failed_at: string
  reason: string
}

export type ShopSourceCandidateStatus = 'pending' | 'stale' | 'hidden' | 'archived' | 'approved'

export interface ShopSourceCandidate {
  id: number
  source: string
  source_id: string
  source_type: SourceType
  display_name: string
  address: string | null
  website_url: string | null
  rubrics: string | null
  status: ShopSourceCandidateStatus
  has_products: boolean
  has_prices: boolean
  has_website: boolean
  product_count: number
  priced_product_count: number
  priority: number
  priority_reason: string
  last_seen_at: string | null
  last_checked_at: string | null
  missing_since: string | null
  approved_shop_id: number | null
  official_strategy: {
    source: string
    source_type: SourceType
    label: string
    status: string
  } | null
  official_source_shop_id: number | null
  official_source_status: string | null
  official_source_last_scraped_at: string | null
  suggested_identity: {
    id: number
    display_name: string
    status: IdentityStatus
    source_count: number
    reason: string
  } | null
  scrape_result: {
    shop_id?: number
    source?: string
    source_type?: SourceType
    status: string
    duration_seconds?: number
    products_seen?: number
    products_saved?: number
    price_snapshots_saved?: number
    task_id?: string
    reason?: string
    error?: string
  } | null
}

export interface ShopSourceCandidateGroup {
  key: string
  label: string
  official_strategy: ShopSourceCandidate['official_strategy']
  candidate_ids: number[]
  size: number
  pending_count: number
  has_prices: boolean
  has_website: boolean
  priority: number
  items: ShopSourceCandidate[]
}

export interface ShopSourceCandidateListResponse {
  items: ShopSourceCandidate[]
  groups: ShopSourceCandidateGroup[]
}

export interface AsyncOperationAcceptedResponse {
  operation: string
  status: 'queued'
  task_id: string
  candidate_id?: number | null
}

export interface OperationStatusResponse<T = unknown> {
  task_id: string
  status: 'queued' | 'running' | 'success' | 'failed'
  celery_state: string
  result?: T
  error?: string
}

export interface ShopSourceCandidateRefreshResult {
  checked: number
  created: number
  updated: number
  stale: number
  skipped_approved: number
  items: number
}

export interface ShopSourceCandidateVerificationResult {
  candidate_id: number
  website_found: boolean
  products_found: boolean
  website_url: string | null
  product_count: number
  priced_product_count: number
}

export interface OfficialStrategyMaterializeResponse {
  source: string
  shop: {
    id: number
    shop_identity_id: number | null
    source: string
    source_id: string
    source_type: SourceType
    name: string
    scrape_status: string
    last_scraped_at: string | null
  }
  identity: {
    id: number
    display_name: string
    preferred_source: string | null
    status: IdentityStatus
  }
  related_candidate_ids: number[]
  scrape_result: ShopSourceCandidate['scrape_result']
}

export interface ShopSourceCandidateListParams {
  status?: ShopSourceCandidateStatus | ''
  includeApproved?: boolean
}

export interface ProductSearchParams {
  q?: string
  categoryId?: number
  uncategorized?: boolean
  shopId?: number
  sort?: ProductSort
  limit?: number
  offset?: number
}

export interface ProductNormalizationQueueParams {
  state?: ProductNormalizationState
  source?: string
  shopId?: number
  categoryId?: number
  q?: string
  limit?: number
  offset?: number
}

export interface CanonicalProductListParams {
  q?: string
  categoryId?: number
  matchStatus?: string
  limit?: number
  offset?: number
}

export interface ScrapeStatusCount {
  status: string
  count: number
}

export interface CatalogPipelineStatusCount {
  stage: string
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
  catalog_pipeline_status_counts: CatalogPipelineStatusCount[]
}

export interface ScrapeHealthParams {
  source?: string
  shopId?: number
  status?: string
  limit?: number
  includeCatalogPipeline?: boolean
}

export interface ShopListParams {
  source?: string
  status?: string
  sourceType?: SourceType | ''
  identityId?: number
  identity?: 'linked' | 'unlinked' | ''
}

export interface ShopIdentityListParams {
  status?: IdentityStatus | ''
}

export interface ShopIdentitySavePayload {
  display_name?: string
  address?: string | null
  website_url?: string | null
  preferred_source?: string | null
  status?: IdentityStatus
  notes?: string | null
  locked_fields?: Record<string, unknown> | null
}

export interface UncategorizedCategoryGroup {
  source: string
  shop_id: number
  shop_name: string
  shop_source_id: string
  category_raw: string | null
  count: number
  titles: string[]
}

export interface CategoryQualityResponse {
  total_products: number
  categorized_products: number
  uncategorized_products: number
  coverage_pct: string
  groups: UncategorizedCategoryGroup[]
}

export interface CategoryQualityParams {
  source?: string
  shopId?: number
  limitGroups?: number
  titlesPerGroup?: number
}

export type CatalogQualitySeverity = 'blocker' | 'warning'

export interface CatalogQualityFinding {
  code: string
  severity: CatalogQualitySeverity
  reason: string
  recommended_action: string
  source_product_id: number | null
  canonical_product_id: number | null
  shop_id: number | null
  related_source_product_ids: number[]
  related_canonical_product_ids: number[]
  metadata: Record<string, unknown> | null
}

export interface CatalogQualityFindingPage {
  items: CatalogQualityFinding[]
  total: number
  limit: number
  offset: number
}

export interface CatalogQualitySummary {
  total: number
  blockers: number
  warnings: number
  by_code: Record<string, number>
}

export interface CatalogQualityFindingsResponse {
  summary: CatalogQualitySummary
  findings: CatalogQualityFindingPage
}

export interface CatalogQualityFindingsParams {
  severity?: CatalogQualitySeverity
  code?: string
  limit?: number
  offset?: number
}

export interface MatchCandidateProduct {
  id: number
  source: string
  shop_id: number
  shop_name: string
  shop_source_id: string
  title: string
  normalized_title: string
  category_id: number | null
  category_raw: string | null
}

export interface MatchCandidateReason {
  method: string
  exact_title: boolean
  matched_normalized_title: string | null
  token_overlap: string[]
  left_only_tokens: string[]
  right_only_tokens: string[]
  ignored_tokens: string[]
  blocked_by: string[]
  token_similarity: number
  same_category: boolean | null
}

export interface MatchCandidatePair {
  left: MatchCandidateProduct
  right: MatchCandidateProduct
  confidence: number
  reason: MatchCandidateReason
}

export interface MatchCandidateResponse {
  products_considered: number
  candidates: MatchCandidatePair[]
}

export interface MatchCandidateParams {
  source?: string
  shopId?: number
  categoryRaw?: string
  minConfidence?: number
  maxConfidence?: number
  limit?: number
  allowCategoryMismatch?: boolean
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

async function writeJson<T>(
  path: string,
  init: RequestInit,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(apiPath(path), {
    ...init,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...init.headers,
    },
    signal,
  })

  if (!response.ok) {
    throw new Error(`API request failed with ${response.status}`)
  }

  return response.json() as Promise<T>
}

function appendOptionalParam(params: URLSearchParams, key: string, value: string | number | boolean | undefined): void {
  if (value !== undefined && value !== '') {
    params.set(key, String(value))
  }
}

function workflowParams(filters: CatalogWorkflowQueueParams): URLSearchParams {
  const params = new URLSearchParams()
  appendOptionalParam(params, 'source', filters.source)
  appendOptionalParam(params, 'shop', filters.shopId)
  appendOptionalParam(params, 'category_id', filters.categoryId)
  appendOptionalParam(params, 'q', filters.q?.trim())
  return params
}

export function fetchProducts(
  filters: ProductSearchParams,
  signal?: AbortSignal,
): Promise<ProductSearchResponse> {
  const params = new URLSearchParams()
  appendOptionalParam(params, 'q', filters.q?.trim())
  appendOptionalParam(params, 'category_id', filters.categoryId)
  appendOptionalParam(params, 'uncategorized', filters.uncategorized ? 'true' : undefined)
  appendOptionalParam(params, 'shop', filters.shopId)
  appendOptionalParam(params, 'sort', filters.sort)
  appendOptionalParam(params, 'limit', filters.limit)
  appendOptionalParam(params, 'offset', filters.offset)

  return fetchJson<ProductSearchResponse>(`/products?${params.toString()}`, signal)
}

export function fetchProductNormalizationQueue(
  filters: ProductNormalizationQueueParams,
  signal?: AbortSignal,
): Promise<ProductNormalizationQueueResponse> {
  const params = new URLSearchParams()
  appendOptionalParam(params, 'state', filters.state)
  appendOptionalParam(params, 'source', filters.source)
  appendOptionalParam(params, 'shop', filters.shopId)
  appendOptionalParam(params, 'category_id', filters.categoryId)
  appendOptionalParam(params, 'q', filters.q?.trim())
  appendOptionalParam(params, 'limit', filters.limit)
  appendOptionalParam(params, 'offset', filters.offset)

  return fetchJson<ProductNormalizationQueueResponse>(
    `/product-normalization/queue?${params.toString()}`,
    signal,
  )
}

function patronReviewQuery(params?: PatronReviewParams): string {
  const query = new URLSearchParams()
  appendOptionalParam(query, 'mode', params?.mode)
  appendOptionalParam(query, 'min_probability', params?.minProbability)
  const value = query.toString()
  return value ? `?${value}` : ''
}

export function fetchPatronReviewItem(
  params?: PatronReviewParams,
  signal?: AbortSignal,
): Promise<PatronReviewPageResponse> {
  return fetchJson<PatronReviewPageResponse>(`/patron-review${patronReviewQuery(params)}`, signal)
}

export function decidePatronReviewItem(
  productId: number,
  action: PatronReviewAction,
  actor: string,
  reason?: string,
  params?: PatronReviewParams,
  signal?: AbortSignal,
): Promise<PatronReviewDecisionResponse> {
  return writeJson<PatronReviewDecisionResponse>(
    `/patron-review/${productId}/decision${patronReviewQuery(params)}`,
    {
      method: 'POST',
      body: JSON.stringify({
        action,
        actor: actor.trim() || 'admin',
        reason: reason?.trim() || null,
      }),
    },
    signal,
  )
}

export function undoPatronReviewDecision(
  actor: string,
  reason?: string,
  params?: PatronReviewParams,
  signal?: AbortSignal,
): Promise<PatronReviewDecisionResponse> {
  return writeJson<PatronReviewDecisionResponse>(
    `/patron-review/undo${patronReviewQuery(params)}`,
    {
      method: 'POST',
      body: JSON.stringify({
        actor: actor.trim() || 'admin',
        reason: reason?.trim() || null,
      }),
    },
    signal,
  )
}

export function fetchCatalogWorkflowDashboard(
  filters: CatalogWorkflowQueueParams = {},
  signal?: AbortSignal,
): Promise<CatalogWorkflowDashboardResponse> {
  const params = workflowParams(filters)
  const query = params.toString()

  return fetchJson<CatalogWorkflowDashboardResponse>(
    query ? `/catalog-workflows/dashboard?${query}` : '/catalog-workflows/dashboard',
    signal,
  )
}

export function fetchCatalogWorkflowQueue(
  queue: CatalogWorkflowQueueName,
  filters: CatalogWorkflowQueueParams = {},
  signal?: AbortSignal,
): Promise<CatalogWorkflowQueueResponse> {
  const params = workflowParams(filters)
  appendOptionalParam(params, 'limit', filters.limit)
  appendOptionalParam(params, 'offset', filters.offset)

  return fetchJson<CatalogWorkflowQueueResponse>(
    `/catalog-workflows/queues/${queue}?${params.toString()}`,
    signal,
  )
}

export function autoAcceptCatalogWorkflowItems(
  payload: CatalogWorkflowAutoAcceptRequest,
  signal?: AbortSignal,
): Promise<CatalogWorkflowAutoAcceptResponse> {
  return writeJson<CatalogWorkflowAutoAcceptResponse>(
    '/catalog-workflows/batches/auto-accept',
    {
      method: 'POST',
      body: JSON.stringify({
        source: payload.source || null,
        shop_id: payload.shopId ?? null,
        category_id: payload.categoryId ?? null,
        q: payload.q?.trim() || null,
        limit: payload.limit ?? 50,
        offset: payload.offset ?? 0,
        dry_run: payload.dryRun ?? true,
        actor: 'admin',
        reason: payload.reason || null,
      }),
    },
    signal,
  )
}

export function fetchCanonicalProducts(
  filters: CanonicalProductListParams = {},
  signal?: AbortSignal,
): Promise<CanonicalProductListResponse> {
  const params = new URLSearchParams()
  appendOptionalParam(params, 'q', filters.q?.trim())
  appendOptionalParam(params, 'category_id', filters.categoryId)
  appendOptionalParam(params, 'match_status', filters.matchStatus)
  appendOptionalParam(params, 'limit', filters.limit)
  appendOptionalParam(params, 'offset', filters.offset)
  const query = params.toString()

  return fetchJson<CanonicalProductListResponse>(
    query ? `/canonical-products?${query}` : '/canonical-products',
    signal,
  )
}

export function fetchCanonicalProduct(
  canonicalProductId: number,
  signal?: AbortSignal,
): Promise<CanonicalProductDetail> {
  return fetchJson<CanonicalProductDetail>(`/canonical-products/${canonicalProductId}`, signal)
}

export function updateCanonicalProduct(
  canonicalProductId: number,
  payload: CanonicalProductUpdatePayload,
  signal?: AbortSignal,
): Promise<CanonicalProductDetail> {
  return writeJson<CanonicalProductDetail>(
    `/canonical-products/${canonicalProductId}`,
    {
      method: 'PATCH',
      body: JSON.stringify(payload),
    },
    signal,
  )
}

export function createCanonicalFromSourceAndAccept(
  sourceProductId: number,
  reason?: string,
  signal?: AbortSignal,
): Promise<ProductMatchDecision> {
  return writeJson<ProductMatchDecision>(
    `/product-matches/from-source/${sourceProductId}/accept`,
    {
      method: 'POST',
      body: JSON.stringify({ actor: 'admin', reason: reason || null }),
    },
    signal,
  )
}

export function acceptProductMatch(
  canonicalProductId: number,
  sourceProductId: number,
  reason?: string,
  signal?: AbortSignal,
): Promise<ProductMatchDecision> {
  return writeJson<ProductMatchDecision>(
    '/product-matches/accept',
    {
      method: 'POST',
      body: JSON.stringify({
        canonical_product_id: canonicalProductId,
        source_product_id: sourceProductId,
        actor: 'admin',
        reason: reason || null,
      }),
    },
    signal,
  )
}

export function autoAcceptProductMatchCandidates(
  payload: ProductMatchAutoAcceptRequest,
  signal?: AbortSignal,
): Promise<ProductMatchAutoAcceptResponse> {
  return writeJson<ProductMatchAutoAcceptResponse>(
    '/product-matches/auto-accept-candidates',
    {
      method: 'POST',
      body: JSON.stringify({
        source: payload.source || null,
        shop_id: payload.shopId ?? null,
        category_id: payload.categoryId ?? null,
        q: payload.q?.trim() || null,
        min_confidence: payload.minConfidence ?? 1,
        methods: payload.methods ?? ['exact_normalized_title'],
        limit: payload.limit ?? 250,
        dry_run: payload.dryRun ?? true,
        actor: 'admin',
        reason: payload.reason || null,
      }),
    },
    signal,
  )
}

export function bulkNormalizeProducts(
  payload: ProductBulkNormalizationRequest,
  signal?: AbortSignal,
): Promise<ProductBulkNormalizationResponse> {
  return writeJson<ProductBulkNormalizationResponse>(
    '/product-normalization/bulk-create-canonicals',
    {
      method: 'POST',
      body: JSON.stringify({
        source: payload.source || null,
        shop_id: payload.shopId ?? null,
        category_id: payload.categoryId ?? null,
        q: payload.q?.trim() || null,
        limit: payload.limit ?? 50,
        offset: payload.offset ?? 0,
        dry_run: payload.dryRun ?? true,
        actor: 'admin',
        reason: payload.reason || null,
      }),
    },
    signal,
  )
}

export function rejectProductMatch(
  matchId: number,
  reason?: string,
  signal?: AbortSignal,
): Promise<ProductMatchDecision> {
  return writeJson<ProductMatchDecision>(
    `/product-matches/${matchId}/reject`,
    {
      method: 'POST',
      body: JSON.stringify({ actor: 'admin', reason: reason || null }),
    },
    signal,
  )
}

export function fetchProduct(
  productId: number,
  signal?: AbortSignal,
): Promise<ProductSearchItem> {
  return fetchJson<ProductSearchItem>(`/products/${productId}`, signal)
}

export function assignProductCategoryOverride(
  productId: number,
  categoryId: number,
  reasonOrSignal?: string | AbortSignal,
  signal?: AbortSignal,
): Promise<ProductSearchItem> {
  const reason = typeof reasonOrSignal === 'string' ? reasonOrSignal.trim() : ''
  const requestSignal = typeof reasonOrSignal === 'string' ? signal : reasonOrSignal

  return writeJson<ProductSearchItem>(
    `/products/${productId}/category-override`,
    {
      method: 'PUT',
      body: JSON.stringify({
        category_id: categoryId,
        actor: 'admin',
        reason: reason || null,
      }),
    },
    requestSignal,
  )
}

export function revertProductCategoryOverride(
  productId: number,
  signal?: AbortSignal,
): Promise<ProductSearchItem> {
  return writeJson<ProductSearchItem>(
    `/products/${productId}/category-override?actor=admin`,
    { method: 'DELETE' },
    signal,
  )
}

export function markProductDataProblem(
  productId: number,
  payload: ProductDataProblemRequest = {},
  signal?: AbortSignal,
): Promise<ProductSearchItem> {
  return writeJson<ProductSearchItem>(
    `/products/${productId}/data-problem`,
    {
      method: 'PUT',
      body: JSON.stringify({
        is_not_product: payload.isNotProduct ?? true,
        actor: 'admin',
        reason: payload.reason?.trim() || null,
      }),
    },
    signal,
  )
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
  appendOptionalParam(params, 'source_type', filters.sourceType)
  appendOptionalParam(params, 'identity_id', filters.identityId)
  appendOptionalParam(params, 'identity', filters.identity)
  const query = params.toString()

  return fetchJson<ShopListResponse>(query ? `/shops?${query}` : '/shops', signal)
}

export function fetchShopIdentities(
  filters: ShopIdentityListParams = {},
  signal?: AbortSignal,
): Promise<ShopIdentityListResponse> {
  const params = new URLSearchParams()
  appendOptionalParam(params, 'status', filters.status)
  const query = params.toString()

  return fetchJson<ShopIdentityListResponse>(
    query ? `/shop-identities?${query}` : '/shop-identities',
    signal,
  )
}

export function createShopIdentity(
  payload: ShopIdentitySavePayload,
  signal?: AbortSignal,
): Promise<ShopIdentity> {
  return writeJson<ShopIdentity>(
    '/shop-identities',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    signal,
  )
}

export function updateShopIdentity(
  identityId: number,
  payload: ShopIdentitySavePayload,
  signal?: AbortSignal,
): Promise<ShopIdentity> {
  return writeJson<ShopIdentity>(
    `/shop-identities/${identityId}`,
    {
      method: 'PATCH',
      body: JSON.stringify(payload),
    },
    signal,
  )
}

export async function deleteShopIdentity(
  identityId: number,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(apiPath(`/shop-identities/${identityId}`), {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
    signal,
  })

  if (!response.ok) {
    throw new Error(`API request failed with ${response.status}`)
  }
}

export function linkShopSource(
  identityId: number,
  shopId: number,
  signal?: AbortSignal,
): Promise<ShopListItem> {
  return writeJson<ShopListItem>(
    `/shop-identities/${identityId}/sources/${shopId}`,
    { method: 'POST' },
    signal,
  )
}

export function unlinkShopSource(
  shopId: number,
  signal?: AbortSignal,
): Promise<ShopListItem> {
  return writeJson<ShopListItem>(
    `/shops/${shopId}/identity`,
    { method: 'DELETE' },
    signal,
  )
}

export function enableTwogisLargeCatalog(
  shopId: number,
  signal?: AbortSignal,
): Promise<ShopListItem> {
  return writeJson<ShopListItem>(
    `/shops/${shopId}/twogis-large-catalog/enable`,
    { method: 'POST' },
    signal,
  )
}

export function disableTwogisLargeCatalog(
  shopId: number,
  signal?: AbortSignal,
): Promise<ShopListItem> {
  return writeJson<ShopListItem>(
    `/shops/${shopId}/twogis-large-catalog/disable`,
    { method: 'POST' },
    signal,
  )
}

export function retryShopScrape(
  shopId: number,
  signal?: AbortSignal,
): Promise<ShopScrapeRetryResponse> {
  return writeJson<ShopScrapeRetryResponse>(
    `/shops/${shopId}/scrape/retry`,
    { method: 'POST' },
    signal,
  )
}

export function fetchShopSourceCandidates(
  filters: ShopSourceCandidateListParams = {},
  signal?: AbortSignal,
): Promise<ShopSourceCandidateListResponse> {
  const params = new URLSearchParams()
  appendOptionalParam(params, 'status', filters.status)
  if (filters.includeApproved !== undefined) {
    params.set('include_approved', String(filters.includeApproved))
  }
  const query = params.toString()

  return fetchJson<ShopSourceCandidateListResponse>(
    query ? `/shop-source-candidates?${query}` : '/shop-source-candidates',
    signal,
  )
}

export function refreshShopSourceCandidates(
  signal?: AbortSignal,
): Promise<AsyncOperationAcceptedResponse> {
  return writeJson<AsyncOperationAcceptedResponse>(
    '/shop-source-candidates/refresh',
    { method: 'POST' },
    signal,
  )
}

export function approveShopSourceCandidate(
  candidateId: number,
  shopIdentityId?: number,
  signal?: AbortSignal,
): Promise<ShopSourceCandidate> {
  return writeJson<ShopSourceCandidate>(
    `/shop-source-candidates/${candidateId}/approve`,
    {
      method: 'POST',
      body: JSON.stringify({ shop_identity_id: shopIdentityId ?? null }),
    },
    signal,
  )
}

export function verifyShopSourceCandidateTwogisData(
  candidateId: number,
  signal?: AbortSignal,
): Promise<AsyncOperationAcceptedResponse> {
  return writeJson<AsyncOperationAcceptedResponse>(
    `/shop-source-candidates/${candidateId}/verify-twogis-data`,
    { method: 'POST' },
    signal,
  )
}

export function fetchOperationStatus<T = unknown>(
  taskId: string,
  signal?: AbortSignal,
): Promise<OperationStatusResponse<T>> {
  return fetchJson<OperationStatusResponse<T>>(`/operations/${taskId}`, signal)
}

export function materializeOfficialStrategy(
  source: string,
  runScrape = true,
  signal?: AbortSignal,
): Promise<OfficialStrategyMaterializeResponse> {
  return writeJson<OfficialStrategyMaterializeResponse>(
    `/shop-source-candidates/official-strategies/${source}/materialize`,
    {
      method: 'POST',
      body: JSON.stringify({ run_scrape: runScrape }),
    },
    signal,
  )
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
  appendOptionalParam(params, 'include_catalog_pipeline', filters.includeCatalogPipeline)
  const query = params.toString()

  return fetchJson<ScrapeHealthResponse>(query ? `/scrapes/health?${query}` : '/scrapes/health', signal)
}

export function fetchCategoryQuality(
  filters: CategoryQualityParams = {},
  signal?: AbortSignal,
): Promise<CategoryQualityResponse> {
  const params = new URLSearchParams()
  appendOptionalParam(params, 'source', filters.source)
  appendOptionalParam(params, 'shop', filters.shopId)
  appendOptionalParam(params, 'limit_groups', filters.limitGroups)
  appendOptionalParam(params, 'titles_per_group', filters.titlesPerGroup)
  const query = params.toString()

  return fetchJson<CategoryQualityResponse>(query ? `/categories/quality?${query}` : '/categories/quality', signal)
}

export function fetchCatalogQualityFindings(
  filters: CatalogQualityFindingsParams = {},
  signal?: AbortSignal,
): Promise<CatalogQualityFindingsResponse> {
  const params = new URLSearchParams()
  appendOptionalParam(params, 'severity', filters.severity)
  appendOptionalParam(params, 'code', filters.code)
  appendOptionalParam(params, 'limit', filters.limit)
  appendOptionalParam(params, 'offset', filters.offset)
  const query = params.toString()

  return fetchJson<CatalogQualityFindingsResponse>(
    query ? `/catalog-quality/findings?${query}` : '/catalog-quality/findings',
    signal,
  )
}

export function fetchMatchCandidates(
  filters: MatchCandidateParams = {},
  signal?: AbortSignal,
): Promise<MatchCandidateResponse> {
  const params = new URLSearchParams()
  appendOptionalParam(params, 'source', filters.source)
  appendOptionalParam(params, 'shop', filters.shopId)
  appendOptionalParam(params, 'category_raw', filters.categoryRaw)
  appendOptionalParam(params, 'min_confidence', filters.minConfidence)
  appendOptionalParam(params, 'max_confidence', filters.maxConfidence)
  appendOptionalParam(params, 'limit', filters.limit)
  if (filters.allowCategoryMismatch !== undefined) {
    params.set('allow_category_mismatch', String(filters.allowCategoryMismatch))
  }
  const query = params.toString()

  return fetchJson<MatchCandidateResponse>(query ? `/matches/candidates?${query}` : '/matches/candidates', signal)
}
