<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { useToast } from '@nuxt/ui/composables'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import {
  acceptProductMatch,
  assignProductCategoryOverride,
  autoAcceptCatalogWorkflowItems,
  createCanonicalFromSourceAndAccept,
  fetchCanonicalProducts,
  fetchCatalogWorkflowQueue,
  fetchCategories,
  markProductDataProblem,
  rejectProductMatch,
  type CanonicalProductListItem,
  type CatalogWorkflowAutoAcceptItem,
  type CatalogWorkflowAutoAcceptResponse,
  type CatalogWorkflowQueueItem,
  type CatalogWorkflowQueueName,
  type CatalogWorkflowReason,
  type CategoryTreeItem,
  type ProductMatchDecision,
  type ProductNormalizationCandidateMatch,
} from '../lib/api'
import { icons } from '../lib/icons'
import { toastError, toastSuccess, toastWarning } from '../lib/notifications'

interface QueueMeta {
  queue: CatalogWorkflowQueueName
  label: string
  eyebrow: string
  empty: string
  icon: typeof icons.check
}

interface CategoryOption {
  id: number
  label: string
}

interface AttributeRow {
  key: string
  label: string
  value: string
  detail: string
}

interface ReviewSignal {
  key: string
  label: string
  value: string
  tone: string
}

const queueMeta: QueueMeta[] = [
  {
    queue: 'auto_acceptable',
    label: 'Можно принять',
    eyebrow: 'Очереди обработки',
    empty: 'Нет карточек для автоматического принятия.',
    icon: icons.check,
  },
  {
    queue: 'review_needed',
    label: 'Нужна проверка',
    eyebrow: 'Ручная проверка',
    empty: 'Нет карточек на ручную проверку.',
    icon: icons.listCheck,
  },
  {
    queue: 'data_problems',
    label: 'Проблемы данных',
    eyebrow: 'Контроль качества',
    empty: 'Нет активных проблем данных.',
    icon: icons.alertTriangle,
  },
  {
    queue: 'possible_duplicates',
    label: 'Похожие товары',
    eyebrow: 'Сверка дублей',
    empty: 'Нет товаров, которые нужно сверить со связанными карточками.',
    icon: icons.gitCompare,
  },
  {
    queue: 'normalized_items',
    label: 'В каталоге',
    eyebrow: 'Нормализованный каталог',
    empty: 'Пока нет связанных офферов.',
    icon: icons.tags,
  },
]

const reviewQueues: CatalogWorkflowQueueName[] = [
  'review_needed',
  'possible_duplicates',
  'data_problems',
]

const stageLabels: Record<string, string> = {
  pipeline: 'Пайплайн',
  catalog_eligibility: 'Допуск',
  cleanup: 'Очистка',
  attributes: 'Атрибуты',
  categorization: 'Категория',
  normalization: 'Нормализация',
}

const route = useRoute()
const toast = useToast()
const items = ref<CatalogWorkflowQueueItem[]>([])
const total = ref(0)
const categories = ref<CategoryTreeItem[]>([])
const isLoading = ref(false)
const isLoadingCategories = ref(false)
const isBatching = ref(false)
const busyAction = ref('')
const errorMessage = ref('')
const searchQuery = ref('')
const batchPreview = ref<CatalogWorkflowAutoAcceptResponse | null>(null)
const reasonByProductId = reactive<Record<number, string>>({})
const categoryByProductId = reactive<Record<number, string>>({})
const dataProblemReasonByProductId = reactive<Record<number, string>>({})
const canonicalSearchByProductId = reactive<Record<number, string>>({})
const selectedCanonicalByProductId = reactive<Record<number, string>>({})
const canonicalResultsByProductId = reactive<Record<number, CanonicalProductListItem[]>>({})

let queueRequest: AbortController | null = null

const queue = computed<CatalogWorkflowQueueName>(() => {
  const value = Array.isArray(route.params.queue) ? route.params.queue[0] : route.params.queue
  return isQueueName(value) ? value : 'auto_acceptable'
})

const activeMeta = computed(() => {
  return queueMeta.find((item) => item.queue === queue.value) ?? queueMeta[0]
})

const canBatchAccept = computed(() => queue.value === 'auto_acceptable')
const isReviewWorkspace = computed(() => reviewQueues.includes(queue.value))

const leafCategoryOptions = computed(() => {
  const options: CategoryOption[] = []

  function walk(categoryItems: CategoryTreeItem[], path: string[]): void {
    for (const category of categoryItems) {
      const nextPath = [...path, category.name]
      if (category.children.length === 0) {
        options.push({ id: category.id, label: nextPath.join(' / ') })
      } else {
        walk(category.children, nextPath)
      }
    }
  }

  walk(categories.value, [])
  return options
})

function isQueueName(value: unknown): value is CatalogWorkflowQueueName {
  return typeof value === 'string' && queueMeta.some((item) => item.queue === value)
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function asString(value: unknown): string | null {
  if (typeof value === 'string' && value.trim()) {
    return value.trim()
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  return null
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }

  return value
    .map((item) => asString(item))
    .filter((item): item is string => item !== null)
}

function confidencePercent(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  const numeric = Number(value)
  return Number.isFinite(numeric) ? `${Math.round(numeric * 100)}%` : String(value)
}

function reasonText(reason: CatalogWorkflowReason): string {
  const parts = [
    reason.status,
    reason.action,
    ...reason.reasons,
    ...reason.blockers,
    reason.message,
  ].filter(Boolean)
  return parts.length ? parts.join(' · ') : 'без деталей'
}

function primaryReason(item: CatalogWorkflowQueueItem): CatalogWorkflowReason | null {
  return item.reasons.find((reason) => reason.stage === 'normalization')
    ?? item.reasons.find((reason) => reason.stage === 'pipeline')
    ?? item.reasons[0]
    ?? null
}

function primarySignalText(item: CatalogWorkflowQueueItem): string {
  const reason = primaryReason(item)
  return reason ? reasonText(reason) : 'Нет данных пайплайна'
}

function primaryActionLabel(item: CatalogWorkflowQueueItem): string {
  return actionLabel(primaryReason(item)?.action ?? null)
}

function canResolveAsProduct(item: CatalogWorkflowQueueItem): boolean {
  return item.queue !== 'data_problems' && !item.is_not_product
}

function formatPrice(item: CatalogWorkflowQueueItem): string {
  if (!item.latest_price) {
    return 'Нет цены'
  }
  if (item.latest_price.price === null) {
    return item.latest_price.unit_raw ? `Цена не указана · ${item.latest_price.unit_raw}` : 'Цена не указана'
  }

  const value = new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: item.latest_price.currency,
    maximumFractionDigits: 2,
  }).format(Number(item.latest_price.price))
  const prefix = item.latest_price.price_kind === 'from' || item.latest_price.price_kind === 'range' ? 'от ' : ''
  return item.latest_price.unit_raw
    ? `${prefix}${value} · ${item.latest_price.unit_raw}`
    : `${prefix}${value}`
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function actionLabel(action: string | null): string {
  const labels: Record<string, string> = {
    attach_to_existing: 'Связать',
    create_normalized_product: 'Создать',
    needs_review: 'Проверить',
    quarantine: 'Исключить',
    accepted: 'Принято',
  }
  return action ? (labels[action] ?? action) : 'Нет действия'
}

function batchStatusClass(status: CatalogWorkflowAutoAcceptItem['status']): string {
  if (status === 'accepted' || status === 'would_accept') {
    return 'border-admin-success-border bg-admin-success-soft text-admin-success'
  }
  return 'border-admin-border-strong bg-admin-surface text-admin-text-muted'
}

function batchStatusLabel(status: CatalogWorkflowAutoAcceptItem['status']): string {
  const labels: Record<CatalogWorkflowAutoAcceptItem['status'], string> = {
    would_accept: 'Можно принять',
    accepted: 'Принято',
    skipped: 'Пропущено',
  }
  return labels[status]
}

function qualityStage(item: CatalogWorkflowQueueItem, stage: string): Record<string, unknown> | null {
  const quality = asRecord(item.catalog_quality)
  return asRecord(quality?.[stage])
}

function attributeRows(item: CatalogWorkflowQueueItem): AttributeRow[] {
  const stage = qualityStage(item, 'attributes')
  const rawItems = Array.isArray(stage?.items) ? stage.items : []
  return rawItems.flatMap((rawItem, index) => {
    const attribute = asRecord(rawItem)
    if (!attribute) {
      return []
    }

    const kind = asString(attribute.kind) ?? 'attribute'
    const raw = asString(attribute.raw)
    const values = asStringList(attribute.values)
    const normalized = asString(attribute.normalized)
    const unit = asString(attribute.unit)
    const value = raw ?? (values.length ? values.join(', ') : null) ?? normalized ?? '-'
    const detail = [
      unit,
      normalized && normalized !== value ? normalized : null,
      confidencePercent(asString(attribute.confidence)),
      asString(attribute.reason),
    ].filter(Boolean).join(' · ')

    return [{
      key: `${kind}:${index}`,
      label: kind,
      value,
      detail,
    }]
  })
}

function reviewSignals(item: CatalogWorkflowQueueItem): ReviewSignal[] {
  const signals: ReviewSignal[] = []
  const attributes = attributeRows(item)
  const categoryStage = qualityStage(item, 'categorization')
  const normalizationStage = qualityStage(item, 'normalization')

  if (attributes.length) {
    signals.push({
      key: `${item.id}:attributes`,
      label: 'Атрибуты',
      value: attributes.map((attribute) => attribute.value).join(', '),
      tone: 'border-admin-success-border bg-admin-success-soft text-admin-success',
    })
  }

  const categorySlug = asString(categoryStage?.category_slug)
  if (item.category?.name || categorySlug) {
    signals.push({
      key: `${item.id}:category`,
      label: 'Категория',
      value: item.category?.name ?? categorySlug ?? 'назначена',
      tone: 'border-admin-border-strong bg-admin-surface-muted text-admin-text',
    })
  }

  const action = asString(normalizationStage?.action)
  if (action) {
    signals.push({
      key: `${item.id}:normalization-action`,
      label: 'Действие',
      value: actionLabel(action),
      tone: 'border-admin-border-strong bg-admin-surface-muted text-admin-link',
    })
  }

  for (const reason of item.reasons) {
    signals.push({
      key: `${item.id}:${reason.stage}:${reason.status ?? 'signal'}`,
      label: stageLabels[reason.stage] ?? reason.stage,
      value: reasonText(reason),
      tone: 'border-admin-border-strong bg-admin-surface text-admin-text-muted',
    })
  }

  return signals.length
    ? signals
    : [{
        key: `${item.id}:empty`,
        label: 'Сигнал',
        value: 'Нет данных пайплайна',
        tone: 'border-admin-border-strong bg-admin-surface text-admin-text-muted',
      }]
}

function reviewConflicts(item: CatalogWorkflowQueueItem): ReviewSignal[] {
  const conflicts: ReviewSignal[] = []
  const normalizationStage = qualityStage(item, 'normalization')
  const blockers = asStringList(normalizationStage?.blockers)

  if (!item.latest_price || item.latest_price.price === null) {
    conflicts.push({
      key: `${item.id}:missing-price`,
      label: 'Цена',
      value: 'нет цены',
      tone: 'border-admin-danger-border bg-admin-danger-soft text-admin-danger',
    })
  }

  if (!item.category_id) {
    conflicts.push({
      key: `${item.id}:missing-category`,
      label: 'Категория',
      value: item.category_raw ? `только исходная: ${item.category_raw}` : 'не назначена',
      tone: 'border-admin-danger-border bg-admin-danger-soft text-admin-danger',
    })
  }

  if (item.is_not_product) {
    conflicts.push({
      key: `${item.id}:not-product`,
      label: 'Тип карточки',
      value: 'не товар',
      tone: 'border-admin-danger-border bg-admin-danger-soft text-admin-danger',
    })
  }

  for (const blocker of blockers) {
    conflicts.push({
      key: `${item.id}:blocker:${blocker}`,
      label: 'Блокер',
      value: blocker,
      tone: 'border-admin-danger-border bg-admin-danger-soft text-admin-danger',
    })
  }

  return conflicts.length
    ? conflicts
    : [{
        key: `${item.id}:no-conflict`,
        label: 'Конфликтов нет',
        value: 'явных блокеров не найдено',
        tone: 'border-admin-border-strong bg-admin-surface text-admin-text-muted',
      }]
}

function suggestedNormalizedProduct(item: CatalogWorkflowQueueItem): string {
  if (item.queue === 'data_problems') {
    return item.is_not_product ? 'Оставить вне каталога' : 'Исправить данные перед решением'
  }

  const normalizationStage = qualityStage(item, 'normalization')
  return asString(normalizationStage?.canonical_title)
    ?? item.match_summary.accepted_canonical_title
    ?? item.candidate_matches[0]?.canonical_title
    ?? 'Создать новый нормализованный товар'
}

function matchReason(match: ProductNormalizationCandidateMatch): Record<string, unknown> | null {
  return asRecord(match.reason)
}

function matchEvidence(match: ProductNormalizationCandidateMatch): string[] {
  const reason = matchReason(match)
  const values = [
    `уверенность ${confidencePercent(match.confidence)}`,
    asString(reason?.exact_title) === 'true' ? 'точное название' : null,
    asString(reason?.same_category) === 'true' ? 'та же категория' : null,
    ...asStringList(reason?.token_overlap).map((token) => `общий токен: ${token}`),
  ].filter((item): item is string => item !== null)
  return values.length ? values : ['нет подробных сигналов']
}

function matchConflicts(match: ProductNormalizationCandidateMatch): string[] {
  const reason = matchReason(match)
  const conflicts = [
    ...asStringList(reason?.blocked_by).map((value) => `блокер: ${value}`),
    ...asStringList(reason?.left_only_tokens).map((value) => `только источник: ${value}`),
    ...asStringList(reason?.right_only_tokens).map((value) => `только каталог: ${value}`),
  ]
  if (asString(reason?.same_category) === 'false') {
    conflicts.push('категории отличаются')
  }
  return conflicts.length ? conflicts : ['явных конфликтов нет']
}

function actionKey(item: CatalogWorkflowQueueItem, action: string): string {
  return `${item.id}:${action}`
}

function isBusy(item: CatalogWorkflowQueueItem, action: string): boolean {
  return busyAction.value === actionKey(item, action)
}

function decisionReason(item: CatalogWorkflowQueueItem): string | undefined {
  return reasonByProductId[item.id]?.trim() || undefined
}

function decisionDescription(decision: ProductMatchDecision): string {
  const action = typeof decision.reason?.action === 'string' ? decision.reason.action : decision.status
  const labels: Record<string, string> = {
    accept: 'Принято',
    reject: 'Отклонено',
    accepted: 'Принято',
    rejected: 'Отклонено',
    supersede: 'Заменено',
  }
  const note = typeof decision.reason?.note === 'string' ? ` · ${decision.reason.note}` : ''
  return `${labels[action] ?? action}${note}`
}

async function loadCategories(): Promise<void> {
  isLoadingCategories.value = true
  try {
    const response = await fetchCategories()
    categories.value = response.items
  } catch (error) {
    toastError(toast, 'Не удалось загрузить категории', error, 'Не удалось загрузить категории')
  } finally {
    isLoadingCategories.value = false
  }
}

async function loadQueue(): Promise<void> {
  queueRequest?.abort()
  const request = new AbortController()
  queueRequest = request
  isLoading.value = true
  errorMessage.value = ''
  batchPreview.value = null

  try {
    const response = await fetchCatalogWorkflowQueue(
      queue.value,
      {
        q: searchQuery.value,
        limit: 50,
        offset: 0,
      },
      request.signal,
    )
    items.value = response.items
    total.value = response.total
    for (const item of response.items) {
      if (item.category_id && !categoryByProductId[item.id]) {
        categoryByProductId[item.id] = String(item.category_id)
      }
      if (!canonicalSearchByProductId[item.id]) {
        canonicalSearchByProductId[item.id] = item.normalized_title
      }
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }

    errorMessage.value = error instanceof Error ? error.message : 'Неизвестная ошибка'
    items.value = []
    total.value = 0
  } finally {
    if (queueRequest === request) {
      isLoading.value = false
    }
  }
}

async function previewBatchAccept(): Promise<void> {
  isBatching.value = true
  batchPreview.value = null

  try {
    const response = await autoAcceptCatalogWorkflowItems({
      q: searchQuery.value,
      limit: 50,
      dryRun: true,
      reason: 'Принято из очереди качества каталога',
    })
    batchPreview.value = response
    if (response.would_accept === 0) {
      toastWarning(toast, 'Нет безопасных решений', 'Текущая очередь не дала карточек для принятия.')
    } else {
      toastSuccess(toast, 'Проверка завершена', `Можно принять: ${response.would_accept}`)
    }
  } catch (error) {
    toastError(toast, 'Не удалось проверить очередь', error, 'Не удалось проверить очередь')
  } finally {
    isBatching.value = false
  }
}

async function applyBatchAccept(): Promise<void> {
  if (!batchPreview.value || batchPreview.value.would_accept === 0) {
    return
  }

  isBatching.value = true
  try {
    const response = await autoAcceptCatalogWorkflowItems({
      q: searchQuery.value,
      limit: 50,
      dryRun: false,
      reason: 'Принято из очереди качества каталога',
    })
    batchPreview.value = response
    toastSuccess(
      toast,
      'Очередь обработана',
      `Принято: ${response.accepted}. Пропущено: ${response.skipped}.`,
    )
    await loadQueue()
  } catch (error) {
    toastError(toast, 'Не удалось применить решения', error, 'Не удалось применить решения')
  } finally {
    isBatching.value = false
  }
}

async function createCanonicalFromItem(item: CatalogWorkflowQueueItem): Promise<void> {
  busyAction.value = actionKey(item, 'create')
  try {
    const decision = await createCanonicalFromSourceAndAccept(item.id, decisionReason(item))
    toastSuccess(toast, 'Решение сохранено', decisionDescription(decision))
    await loadQueue()
  } catch (error) {
    toastError(toast, 'Не удалось создать нормализованный товар', error, 'Не удалось создать нормализованный товар')
  } finally {
    busyAction.value = ''
  }
}

async function acceptCandidateMatch(
  item: CatalogWorkflowQueueItem,
  match: ProductNormalizationCandidateMatch,
): Promise<void> {
  busyAction.value = actionKey(item, `accept:${match.id}`)
  try {
    const decision = await acceptProductMatch(match.canonical_product_id, item.id, decisionReason(item))
    toastSuccess(toast, 'Решение сохранено', decisionDescription(decision))
    await loadQueue()
  } catch (error) {
    toastError(toast, 'Не удалось связать товары', error, 'Не удалось связать товары')
  } finally {
    busyAction.value = ''
  }
}

async function rejectCandidateMatch(
  item: CatalogWorkflowQueueItem,
  match: ProductNormalizationCandidateMatch,
): Promise<void> {
  busyAction.value = actionKey(item, `reject:${match.id}`)
  try {
    const decision = await rejectProductMatch(match.id, decisionReason(item) || 'Не тот товар')
    toastSuccess(toast, 'Решение сохранено', decisionDescription(decision))
    await loadQueue()
  } catch (error) {
    toastError(toast, 'Не удалось отклонить связь', error, 'Не удалось отклонить связь')
  } finally {
    busyAction.value = ''
  }
}

async function searchCanonicalProductsForItem(item: CatalogWorkflowQueueItem): Promise<void> {
  busyAction.value = actionKey(item, 'search')
  try {
    const response = await fetchCanonicalProducts({
      q: canonicalSearchByProductId[item.id] || item.normalized_title,
      matchStatus: 'active',
      limit: 10,
    })
    canonicalResultsByProductId[item.id] = response.items
    if (response.items.length === 1) {
      selectedCanonicalByProductId[item.id] = String(response.items[0].id)
    }
    if (response.items.length === 0) {
      toastWarning(toast, 'Ничего не найдено', 'По этому запросу нет нормализованных товаров.')
    }
  } catch (error) {
    toastError(toast, 'Не удалось найти товары', error, 'Не удалось найти товары')
  } finally {
    busyAction.value = ''
  }
}

async function linkCanonicalProduct(item: CatalogWorkflowQueueItem): Promise<void> {
  const canonicalProductId = Number(selectedCanonicalByProductId[item.id])
  if (!canonicalProductId) {
    toastWarning(toast, 'Выберите товар', 'Сначала выберите нормализованный товар для связи.')
    return
  }

  busyAction.value = actionKey(item, 'link')
  try {
    const decision = await acceptProductMatch(canonicalProductId, item.id, decisionReason(item))
    toastSuccess(toast, 'Решение сохранено', decisionDescription(decision))
    await loadQueue()
  } catch (error) {
    toastError(toast, 'Не удалось связать товар', error, 'Не удалось связать товар')
  } finally {
    busyAction.value = ''
  }
}

async function saveCategoryOverride(item: CatalogWorkflowQueueItem): Promise<void> {
  const categoryId = Number(categoryByProductId[item.id])
  if (!Number.isInteger(categoryId) || categoryId <= 0) {
    toastWarning(toast, 'Выберите категорию', 'Для исправления нужна конечная категория.')
    return
  }

  busyAction.value = actionKey(item, 'category')
  try {
    await assignProductCategoryOverride(item.id, categoryId, decisionReason(item))
    toastSuccess(toast, 'Категория сохранена')
    await loadQueue()
  } catch (error) {
    toastError(toast, 'Не удалось сохранить категорию', error, 'Не удалось сохранить категорию')
  } finally {
    busyAction.value = ''
  }
}

async function markItemDataProblem(item: CatalogWorkflowQueueItem): Promise<void> {
  busyAction.value = actionKey(item, 'data-problem')
  try {
    await markProductDataProblem(item.id, {
      isNotProduct: true,
      reason: dataProblemReasonByProductId[item.id]?.trim() || decisionReason(item) || 'Проблема данных',
    })
    toastSuccess(toast, 'Карточка отправлена в проблемы данных')
    await loadQueue()
  } catch (error) {
    toastError(toast, 'Не удалось пометить проблему', error, 'Не удалось пометить проблему')
  } finally {
    busyAction.value = ''
  }
}

watch(queue, () => {
  void loadQueue()
})

onMounted(() => {
  void loadCategories()
  void loadQueue()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
      <div>
        <p class="inline-flex items-center gap-2 text-sm font-medium text-admin-link">
          <Icon :icon="activeMeta.icon" class="size-4" aria-hidden="true" />
          {{ activeMeta.eyebrow }}
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-admin-text">{{ activeMeta.label }}</h2>
        <p class="mt-2 text-sm leading-6 text-admin-text-muted">
          {{ isLoading ? 'Загрузка...' : `${total} карточек в текущей очереди` }}
        </p>
      </div>

      <div class="flex flex-col gap-2 sm:flex-row">
        <RouterLink
          to="/"
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-admin-border px-4 text-sm font-semibold text-admin-text-muted transition hover:border-admin-border-strong hover:text-admin-text"
        >
          <Icon :icon="icons.layoutDashboard" class="size-4" aria-hidden="true" />
          Сводка
        </RouterLink>
        <button
          v-if="canBatchAccept"
          type="button"
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-admin-primary px-4 text-sm font-semibold text-admin-primary-text transition hover:bg-admin-primary-hover disabled:cursor-wait disabled:opacity-60"
          :disabled="isBatching"
          @click="previewBatchAccept"
        >
          <Icon :icon="icons.check" class="size-4" aria-hidden="true" />
          {{ isBatching ? 'Проверяем...' : 'Проверить страницу' }}
        </button>
      </div>
    </div>

    <div class="flex gap-2 overflow-x-auto pb-1">
      <RouterLink
        v-for="item in queueMeta"
        :key="item.queue"
        :to="`/workflows/queues/${item.queue}`"
        class="inline-flex shrink-0 items-center gap-2 rounded-md border px-3 py-2 text-sm font-semibold transition"
        :class="queue === item.queue ? 'border-admin-primary bg-admin-primary text-admin-primary-text' : 'border-admin-border bg-admin-surface text-admin-text-muted hover:border-admin-border-strong hover:text-admin-text'"
      >
        <Icon :icon="item.icon" class="size-4" aria-hidden="true" />
        {{ item.label }}
      </RouterLink>
    </div>

    <div class="rounded-lg border border-admin-border bg-admin-surface p-4">
      <div class="grid gap-3 sm:grid-cols-[1fr_auto]">
        <label class="relative block">
          <Icon :icon="icons.search" class="pointer-events-none absolute left-3 top-3 size-4 text-admin-text-faint" aria-hidden="true" />
          <input
            v-model="searchQuery"
            type="search"
            class="h-10 w-full rounded-md border border-admin-border bg-admin-surface pl-9 pr-3 text-sm text-admin-text outline-none transition placeholder:text-admin-text-faint focus:border-admin-focus"
            placeholder="Поиск по названию"
            aria-label="Поиск по названию"
            @keyup.enter="loadQueue"
          >
        </label>
        <button
          type="button"
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-admin-border-strong px-4 text-sm font-semibold text-admin-text transition hover:border-admin-primary hover:text-admin-link-hover"
          @click="loadQueue"
        >
          <Icon :icon="icons.filter" class="size-4" aria-hidden="true" />
          Найти
        </button>
      </div>
    </div>

    <div
      v-if="batchPreview"
      class="rounded-lg border border-admin-border-strong bg-admin-surface-muted p-4"
    >
      <div class="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div class="grid gap-3 sm:grid-cols-3">
          <div>
            <p class="text-xs uppercase tracking-wide text-admin-link">На странице</p>
            <p class="mt-1 text-xl font-semibold text-admin-link">{{ batchPreview.page_size }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-admin-link">Принять</p>
            <p class="mt-1 text-xl font-semibold text-admin-link">{{ batchPreview.would_accept }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-admin-link">Пропустить</p>
            <p class="mt-1 text-xl font-semibold text-admin-link">{{ batchPreview.skipped }}</p>
          </div>
        </div>

        <button
          type="button"
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-admin-primary px-4 text-sm font-semibold text-admin-primary-text transition hover:bg-admin-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="isBatching || batchPreview.would_accept === 0"
          @click="applyBatchAccept"
        >
          <Icon :icon="icons.check" class="size-4" aria-hidden="true" />
          {{ isBatching ? 'Применяем...' : `Принять ${batchPreview.would_accept}` }}
        </button>
      </div>

      <div v-if="batchPreview.items.length" class="mt-4 grid gap-2 border-t border-admin-border-strong pt-4">
        <div
          v-for="result in batchPreview.items"
          :key="`${result.source_product_id}:${result.status}`"
          class="grid gap-3 rounded-md border border-admin-border-strong bg-admin-surface-subtle p-3 text-sm md:grid-cols-[1fr_auto]"
        >
          <div class="min-w-0">
            <p class="truncate font-semibold text-admin-text">{{ result.title }}</p>
            <p class="mt-1 text-xs text-admin-text-muted">
              {{ actionLabel(result.action) }} · {{ result.reason }}
            </p>
          </div>
          <span
            class="inline-flex w-fit items-center rounded-md border px-2 py-1 text-xs font-semibold"
            :class="batchStatusClass(result.status)"
          >
            {{ batchStatusLabel(result.status) }}
          </span>
        </div>
      </div>
    </div>

    <div
      v-if="errorMessage"
      class="rounded-lg border border-admin-danger-border bg-admin-danger-soft p-4 text-sm text-admin-danger"
    >
      {{ errorMessage }}
    </div>

    <div v-if="isLoading" class="grid gap-3">
      <div
        v-for="index in 4"
        :key="index"
        class="h-40 animate-pulse rounded-lg border border-admin-border bg-admin-surface"
      />
    </div>

    <div
      v-else-if="items.length === 0 && !errorMessage"
      class="rounded-lg border border-admin-border bg-admin-surface p-6 text-sm text-admin-text-muted"
    >
      {{ activeMeta.empty }}
    </div>

    <div v-else class="grid gap-3">
      <article
        v-for="item in items"
        :key="item.id"
        class="rounded-lg border border-admin-border bg-admin-surface p-4"
      >
        <div class="grid gap-5 2xl:grid-cols-[minmax(0,1fr)_360px]">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <span class="rounded-md border border-admin-border-strong px-2 py-1 text-xs font-medium text-admin-text-muted">
                {{ item.source }}
              </span>
              <span class="text-xs text-admin-text-faint">{{ item.shop.name }}</span>
              <span class="text-xs text-admin-text-faint">{{ formatDateTime(item.last_seen_at) }}</span>
            </div>

            <h3 class="mt-3 text-base font-semibold text-admin-text">{{ item.title }}</h3>
            <p class="mt-1 break-words text-sm text-admin-text-faint">{{ item.normalized_title }}</p>

            <div class="mt-3 flex flex-wrap gap-2 text-xs text-admin-text-muted">
              <span class="rounded-md border border-admin-border bg-admin-surface px-2 py-1">
                {{ item.category?.name ?? item.category_raw ?? 'Без категории' }}
              </span>
              <span class="rounded-md border border-admin-border bg-admin-surface px-2 py-1">
                {{ formatPrice(item) }}
              </span>
              <span class="rounded-md border border-admin-border bg-admin-surface px-2 py-1">
                {{ primaryActionLabel(item) }}
              </span>
            </div>

            <div v-if="isReviewWorkspace" class="mt-5 grid gap-4 xl:grid-cols-2">
              <section>
                <p class="text-xs uppercase tracking-wide text-admin-text-faint">Сигналы</p>
                <div class="mt-2 flex flex-wrap gap-2">
                  <span
                    v-for="signal in reviewSignals(item)"
                    :key="signal.key"
                    class="inline-flex max-w-full items-center gap-2 rounded-md border px-2 py-1 text-xs"
                    :class="signal.tone"
                  >
                    <span class="font-semibold">{{ signal.label }}</span>
                    <span class="truncate">{{ signal.value }}</span>
                  </span>
                </div>
              </section>

              <section>
                <p class="text-xs uppercase tracking-wide text-admin-text-faint">Конфликты</p>
                <div class="mt-2 flex flex-wrap gap-2">
                  <span
                    v-for="conflict in reviewConflicts(item)"
                    :key="conflict.key"
                    class="inline-flex max-w-full items-center gap-2 rounded-md border px-2 py-1 text-xs"
                    :class="conflict.tone"
                  >
                    <span class="font-semibold">{{ conflict.label }}</span>
                    <span class="truncate">{{ conflict.value }}</span>
                  </span>
                </div>
              </section>
            </div>

            <div v-if="isReviewWorkspace" class="mt-5">
              <p class="text-xs uppercase tracking-wide text-admin-text-faint">Извлеченные атрибуты</p>
              <div v-if="attributeRows(item).length" class="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                <div
                  v-for="attribute in attributeRows(item)"
                  :key="attribute.key"
                  class="rounded-md border border-admin-border bg-admin-surface p-3"
                >
                  <p class="text-xs font-semibold uppercase tracking-wide text-admin-text-faint">{{ attribute.label }}</p>
                  <p class="mt-1 text-sm font-semibold text-admin-text">{{ attribute.value }}</p>
                  <p v-if="attribute.detail" class="mt-1 text-xs text-admin-text-faint">{{ attribute.detail }}</p>
                </div>
              </div>
              <p v-else class="mt-2 text-sm text-admin-text-faint">Атрибуты не извлечены.</p>
            </div>

            <div v-if="item.candidate_matches.length" class="mt-5 grid gap-3">
              <p class="text-xs uppercase tracking-wide text-admin-text-faint">Возможные связи</p>
              <div
                v-for="match in item.candidate_matches"
                :key="match.id"
                class="rounded-md border border-admin-border bg-admin-surface p-3"
              >
                <div class="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                  <div class="min-w-0">
                    <RouterLink
                      :to="`/canonical-products/${match.canonical_product_id}`"
                      class="text-sm font-semibold text-admin-text transition hover:text-admin-link-hover"
                    >
                      {{ match.canonical_title }}
                    </RouterLink>
                    <p class="mt-1 break-words text-xs text-admin-text-faint">
                      {{ match.canonical_normalized_title }} · {{ match.method }} · {{ confidencePercent(match.confidence) }}
                    </p>
                  </div>
                  <div v-if="isReviewWorkspace && canResolveAsProduct(item)" class="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      class="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-admin-success px-3 text-sm font-semibold text-admin-primary-text transition hover:bg-admin-success disabled:cursor-wait disabled:opacity-60"
                      :disabled="Boolean(busyAction)"
                      @click="acceptCandidateMatch(item, match)"
                    >
                      <Icon :icon="icons.check" class="size-4" aria-hidden="true" />
                      {{ isBusy(item, `accept:${match.id}`) ? 'Принять...' : 'Принять' }}
                    </button>
                    <button
                      type="button"
                      class="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-admin-border-strong px-3 text-sm font-semibold text-admin-text-muted transition hover:border-admin-danger-border hover:text-admin-danger disabled:cursor-wait disabled:opacity-60"
                      :disabled="Boolean(busyAction)"
                      @click="rejectCandidateMatch(item, match)"
                    >
                      <Icon :icon="icons.x" class="size-4" aria-hidden="true" />
                      {{ isBusy(item, `reject:${match.id}`) ? 'Отклонить...' : 'Отклонить' }}
                    </button>
                  </div>
                  <RouterLink
                    v-else
                    :to="`/canonical-products/${match.canonical_product_id}`"
                    class="inline-flex h-8 items-center justify-center gap-2 rounded-md border border-admin-border-strong px-3 text-sm font-semibold text-admin-text-muted transition hover:border-admin-border-strong hover:text-admin-text"
                  >
                    <Icon :icon="icons.tags" class="size-4" aria-hidden="true" />
                    Каталог
                  </RouterLink>
                </div>

                <div v-if="isReviewWorkspace" class="mt-3 grid gap-3 text-xs lg:grid-cols-2">
                  <div>
                    <p class="font-semibold uppercase tracking-wide text-admin-success">За связь</p>
                    <ul class="mt-1 space-y-1 text-admin-text-muted">
                      <li v-for="evidence in matchEvidence(match)" :key="evidence">{{ evidence }}</li>
                    </ul>
                  </div>
                  <div>
                    <p class="font-semibold uppercase tracking-wide text-admin-danger">Риски</p>
                    <ul class="mt-1 space-y-1 text-admin-text-muted">
                      <li v-for="conflict in matchConflicts(match)" :key="conflict">{{ conflict }}</li>
                    </ul>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <aside class="border-t border-admin-border pt-4 2xl:border-l 2xl:border-t-0 2xl:pl-5 2xl:pt-0">
            <p class="text-xs uppercase tracking-wide text-admin-text-faint">Предлагаемое решение</p>
            <p class="mt-2 text-sm font-semibold text-admin-text">{{ suggestedNormalizedProduct(item) }}</p>
            <p class="mt-2 text-sm text-admin-text-muted">{{ primarySignalText(item) }}</p>
            <RouterLink
              :to="`/products/${item.id}`"
              class="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-admin-link hover:text-admin-link-hover"
            >
              Открыть карточку
              <Icon :icon="icons.chevronRight" class="size-4" aria-hidden="true" />
            </RouterLink>

            <div v-if="isReviewWorkspace" class="mt-4 space-y-4 border-t border-admin-border pt-4">
              <textarea
                v-model="reasonByProductId[item.id]"
                class="min-h-20 w-full rounded-md border border-admin-border bg-admin-surface px-3 py-2 text-sm text-admin-text outline-none transition placeholder:text-admin-text-faint focus:border-admin-focus"
                placeholder="Причина решения"
                aria-label="Причина решения"
              />

              <button
                v-if="canResolveAsProduct(item)"
                type="button"
                class="inline-flex w-full items-center justify-center gap-2 rounded-md bg-admin-primary px-3 py-2 text-sm font-semibold text-admin-primary-text transition hover:bg-admin-primary-hover disabled:cursor-wait disabled:opacity-60"
                :disabled="Boolean(busyAction)"
                @click="createCanonicalFromItem(item)"
              >
                <Icon :icon="icons.plus" class="size-4" aria-hidden="true" />
                {{ isBusy(item, 'create') ? 'Создаем...' : 'Создать новый товар' }}
              </button>

              <div v-if="canResolveAsProduct(item)" class="space-y-2">
                <label class="block text-xs uppercase tracking-wide text-admin-text-faint">
                  Исправить категорию
                </label>
                <select
                  v-model="categoryByProductId[item.id]"
                  class="h-10 w-full rounded-md border border-admin-border bg-admin-surface px-3 text-sm text-admin-text outline-none transition focus:border-admin-focus"
                  :disabled="isLoadingCategories"
                  aria-label="Выбор категории"
                >
                  <option value="">Выберите категорию</option>
                  <option v-for="category in leafCategoryOptions" :key="category.id" :value="String(category.id)">
                    {{ category.label }}
                  </option>
                </select>
                <button
                  type="button"
                  class="inline-flex w-full items-center justify-center gap-2 rounded-md border border-admin-border-strong px-3 py-2 text-sm font-semibold text-admin-text-muted transition hover:border-admin-primary hover:text-admin-link-hover disabled:cursor-wait disabled:opacity-60"
                  :disabled="Boolean(busyAction) || isLoadingCategories"
                  @click="saveCategoryOverride(item)"
                >
                  <Icon :icon="icons.category" class="size-4" aria-hidden="true" />
                  {{ isBusy(item, 'category') ? 'Сохраняем...' : 'Сохранить категорию' }}
                </button>
              </div>

              <div class="space-y-2">
                <label class="block text-xs uppercase tracking-wide text-admin-text-faint">
                  Связать вручную
                </label>
                <div class="grid gap-2">
                  <input
                    v-model="canonicalSearchByProductId[item.id]"
                    type="search"
                    class="h-10 rounded-md border border-admin-border bg-admin-surface px-3 text-sm text-admin-text outline-none transition placeholder:text-admin-text-faint focus:border-admin-focus"
                    :placeholder="item.normalized_title"
                    aria-label="Поиск нормализованного товара"
                    @keyup.enter="searchCanonicalProductsForItem(item)"
                  >
                  <button
                    type="button"
                    class="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-admin-border-strong px-3 text-sm font-semibold text-admin-text-muted transition hover:border-admin-primary hover:text-admin-text disabled:cursor-wait disabled:opacity-60"
                    :disabled="Boolean(busyAction)"
                    @click="searchCanonicalProductsForItem(item)"
                  >
                    <Icon :icon="icons.search" class="size-4" aria-hidden="true" />
                    {{ isBusy(item, 'search') ? 'Ищем...' : 'Найти в каталоге' }}
                  </button>
                </div>

                <select
                  v-if="canonicalResultsByProductId[item.id]?.length"
                  v-model="selectedCanonicalByProductId[item.id]"
                  class="h-10 w-full rounded-md border border-admin-border bg-admin-surface px-3 text-sm text-admin-text outline-none transition focus:border-admin-focus"
                  aria-label="Выбор нормализованного товара"
                >
                  <option value="">Выберите товар</option>
                  <option
                    v-for="canonical in canonicalResultsByProductId[item.id]"
                    :key="canonical.id"
                    :value="String(canonical.id)"
                  >
                    {{ canonical.title }}
                  </option>
                </select>

                <button
                  v-if="canonicalResultsByProductId[item.id]?.length"
                  type="button"
                  class="inline-flex w-full items-center justify-center gap-2 rounded-md bg-admin-primary px-3 py-2 text-sm font-semibold text-admin-primary-text transition hover:bg-admin-primary-hover disabled:cursor-wait disabled:opacity-60"
                  :disabled="Boolean(busyAction) || !selectedCanonicalByProductId[item.id]"
                  @click="linkCanonicalProduct(item)"
                >
                  <Icon :icon="icons.link" class="size-4" aria-hidden="true" />
                  {{ isBusy(item, 'link') ? 'Связываем...' : 'Связать выбранный' }}
                </button>
              </div>

              <div class="space-y-2 border-t border-admin-border pt-4">
                <label class="block text-xs uppercase tracking-wide text-admin-text-faint">
                  Проблема данных
                </label>
                <textarea
                  v-model="dataProblemReasonByProductId[item.id]"
                  class="min-h-16 w-full rounded-md border border-admin-border bg-admin-surface px-3 py-2 text-sm text-admin-text outline-none transition placeholder:text-admin-text-faint focus:border-admin-danger-border"
                  placeholder="Что не так с карточкой"
                  aria-label="Причина проблемы данных"
                />
                <button
                  type="button"
                  class="inline-flex w-full items-center justify-center gap-2 rounded-md border border-admin-danger-border px-3 py-2 text-sm font-semibold text-admin-danger transition hover:border-admin-danger-border disabled:cursor-wait disabled:opacity-60"
                  :disabled="Boolean(busyAction)"
                  @click="markItemDataProblem(item)"
                >
                  <Icon :icon="icons.alertTriangle" class="size-4" aria-hidden="true" />
                  {{ isBusy(item, 'data-problem') ? 'Сохраняем...' : 'Пометить проблему' }}
                </button>
              </div>
            </div>
          </aside>
        </div>
      </article>
    </div>
  </section>
</template>
