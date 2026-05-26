<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { useToast } from '@nuxt/ui/composables'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import {
  acceptProductMatch,
  autoAcceptProductMatchCandidates,
  createCanonicalFromSourceAndAccept,
  fetchCanonicalProducts,
  fetchCategories,
  fetchProductNormalizationQueue,
  fetchShops,
  rejectProductMatch,
  type CanonicalProductListItem,
  type CategoryTreeItem,
  type ProductMatchAutoAcceptRequest,
  type ProductMatchAutoAcceptResponse,
  type ProductMatchDecision,
  type ProductNormalizationCandidateMatch,
  type ProductNormalizationQueueItem,
  type ProductNormalizationState,
  type ShopListItem,
} from '../lib/api'
import { icons } from '../lib/icons'
import { toastError, toastSuccess, toastWarning } from '../lib/notifications'

interface StatusOption {
  value: ProductNormalizationState
  label: string
  hint: string
}

interface CategoryOption {
  id: number
  label: string
}

const statusOptions: StatusOption[] = [
  { value: 'needs_review', label: 'На проверку', hint: 'нужен человек' },
  { value: 'eligible_unmatched', label: 'Можно нормализовать', hint: 'без пары' },
  { value: 'candidate_match', label: 'Есть кандидат', hint: 'сравнить матч' },
  { value: 'accepted', label: 'Связаны', hint: 'уже в каталоге' },
  { value: 'ineligible', label: 'Заблокированы', hint: 'не товар или цена от' },
]

const selectedState = ref<ProductNormalizationState>('needs_review')
const selectedSource = ref('')
const selectedShopId = ref('')
const selectedCategoryId = ref('')
const searchQuery = ref('')
const items = ref<ProductNormalizationQueueItem[]>([])
const total = ref(0)
const shops = ref<ShopListItem[]>([])
const categories = ref<CategoryTreeItem[]>([])
const isLoading = ref(false)
const busyAction = ref('')
const isAutoAccepting = ref(false)
const autoAcceptPreview = ref<ProductMatchAutoAcceptResponse | null>(null)
const toast = useToast()
const reasonByProductId = reactive<Record<number, string>>({})
const canonicalSearchByProductId = reactive<Record<number, string>>({})
const canonicalResultsByProductId = reactive<Record<number, CanonicalProductListItem[]>>({})
const selectedCanonicalByProductId = reactive<Record<number, string>>({})

let queueRequest: AbortController | null = null

const sourceOptions = computed(() => {
  return Array.from(new Set(shops.value.map((shop) => shop.source))).sort()
})

const filteredShopOptions = computed(() => {
  if (!selectedSource.value) {
    return shops.value
  }

  return shops.value.filter((shop) => shop.source === selectedSource.value)
})

const categoryOptions = computed(() => flattenCategories(categories.value))

const activeStatus = computed(() => {
  return statusOptions.find((status) => status.value === selectedState.value) ?? statusOptions[0]
})

const blockedCount = computed(() => {
  return items.value.filter((item) => item.state === 'ineligible').length
})

const workQueueCount = computed(() => {
  return items.value.filter((item) => item.state !== 'ineligible' && item.state !== 'accepted').length
})

const canAutoAccept = computed(() => {
  return selectedState.value === 'eligible_unmatched' || selectedState.value === 'candidate_match'
})

function stateLabel(state: ProductNormalizationState): string {
  return statusOptions.find((status) => status.value === state)?.label ?? state
}

function stateClass(state: ProductNormalizationState): string {
  if (state === 'ineligible') {
    return 'border-red-400/30 bg-red-400/10 text-red-200'
  }
  if (state === 'needs_review') {
    return 'border-amber-400/30 bg-amber-400/10 text-amber-200'
  }
  if (state === 'candidate_match') {
    return 'border-sky-400/30 bg-sky-400/10 text-sky-200'
  }
  if (state === 'accepted') {
    return 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'
  }

  return 'border-neutral-700 bg-neutral-900 text-neutral-300'
}

function categoryLabel(item: ProductNormalizationQueueItem): string {
  if (item.category_name) {
    return item.category_name
  }
  if (item.category_raw) {
    return item.category_raw
  }

  return 'Без категории'
}

function eligibilityReasons(item: ProductNormalizationQueueItem): string[] {
  return item.catalog_eligibility?.reasons.length
    ? item.catalog_eligibility.reasons
    : item.is_not_product
      ? ['карточка помечена как не товар']
      : []
}

function formatPrice(item: ProductNormalizationQueueItem): string {
  if (!item.latest_price) {
    return 'Нет цены'
  }
  if (item.latest_price.price === null) {
    return `Цена не указана${item.latest_price.unit_raw ? ` · ${item.latest_price.unit_raw}` : ''}`
  }

  const value = new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: item.latest_price.currency,
    maximumFractionDigits: 2,
  }).format(Number(item.latest_price.price))
  return item.latest_price.unit_raw ? `${value} · ${item.latest_price.unit_raw}` : value
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

function confidencePercent(value: string): string {
  return `${Math.round(Number(value) * 100)}%`
}

function actionKey(item: ProductNormalizationQueueItem, action: string): string {
  return `${item.id}:${action}`
}

function isBusy(item: ProductNormalizationQueueItem, action: string): boolean {
  return busyAction.value === actionKey(item, action)
}

function decisionDescription(decision: ProductMatchDecision): string {
  const action = typeof decision.reason?.action === 'string' ? decision.reason.action : decision.status
  const actionLabels: Record<string, string> = {
    accept: 'Принято',
    reject: 'Отклонено',
    supersede: 'Заменено',
    accepted: 'Принято',
    rejected: 'Отклонено',
  }
  const note = typeof decision.reason?.note === 'string' ? ` · ${decision.reason.note}` : ''
  return `${actionLabels[action] ?? action}${note}`
}

function skippedAutoAcceptCount(result: ProductMatchAutoAcceptResponse): number {
  return result.skipped_already_accepted
    + result.skipped_ambiguous
    + result.skipped_ineligible
    + result.skipped_category_mismatch
    + result.skipped_low_confidence
    + result.skipped_method
    + result.skipped_previously_rejected
}

function flattenCategories(itemsToFlatten: CategoryTreeItem[], level = 0): CategoryOption[] {
  return itemsToFlatten.flatMap((category) => [
    { id: category.id, label: `${'— '.repeat(level)}${category.name}` },
    ...flattenCategories(category.children, level + 1),
  ])
}

async function loadQueue(): Promise<void> {
  queueRequest?.abort()
  const request = new AbortController()
  queueRequest = request
  isLoading.value = true

  try {
    const [shopResponse, categoryResponse, queueResponse] = await Promise.all([
      fetchShops({}, request.signal),
      fetchCategories(request.signal),
      fetchProductNormalizationQueue(
        {
          state: selectedState.value,
          source: selectedSource.value,
          shopId: selectedShopId.value ? Number(selectedShopId.value) : undefined,
          categoryId: selectedCategoryId.value ? Number(selectedCategoryId.value) : undefined,
          q: searchQuery.value,
          limit: 50,
        },
        request.signal,
      ),
    ])
    shops.value = shopResponse.items
    categories.value = categoryResponse.items
    items.value = queueResponse.items
    total.value = queueResponse.total
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }

    toastError(
      toast,
      'Не удалось загрузить очередь нормализации',
      error,
      'Не удалось загрузить очередь нормализации',
    )
    items.value = []
    total.value = 0
  } finally {
    if (queueRequest === request) {
      isLoading.value = false
    }
  }
}

async function createCanonicalFromItem(item: ProductNormalizationQueueItem): Promise<void> {
  busyAction.value = actionKey(item, 'create')

  try {
    const decision = await createCanonicalFromSourceAndAccept(
      item.id,
      reasonByProductId[item.id],
    )
    toastSuccess(toast, 'Решение сохранено', decisionDescription(decision))
    await loadQueue()
  } catch (error) {
    toastError(
      toast,
      'Не удалось создать нормализованный товар',
      error,
      'Не удалось создать нормализованный товар',
    )
  } finally {
    busyAction.value = ''
  }
}

async function searchCanonicalProductsForItem(item: ProductNormalizationQueueItem): Promise<void> {
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
  } catch (error) {
    toastError(
      toast,
      'Не удалось найти нормализованные товары',
      error,
      'Не удалось найти нормализованные товары',
    )
  } finally {
    busyAction.value = ''
  }
}

async function linkCanonicalProduct(item: ProductNormalizationQueueItem): Promise<void> {
  const canonicalProductId = Number(selectedCanonicalByProductId[item.id])
  if (!canonicalProductId) {
    toastWarning(toast, 'Выберите нормализованный товар', 'Сначала найдите и выберите товар для связи.')
    return
  }

  busyAction.value = actionKey(item, 'link')

  try {
    const decision = await acceptProductMatch(
      canonicalProductId,
      item.id,
      reasonByProductId[item.id],
    )
    toastSuccess(toast, 'Решение сохранено', decisionDescription(decision))
    await loadQueue()
  } catch (error) {
    toastError(toast, 'Не удалось связать товар', error, 'Не удалось связать товар')
  } finally {
    busyAction.value = ''
  }
}

async function acceptCandidateMatch(
  item: ProductNormalizationQueueItem,
  match: ProductNormalizationCandidateMatch,
): Promise<void> {
  busyAction.value = actionKey(item, `accept:${match.id}`)

  try {
    const decision = await acceptProductMatch(
      match.canonical_product_id,
      item.id,
      reasonByProductId[item.id],
    )
    toastSuccess(toast, 'Решение сохранено', decisionDescription(decision))
    await loadQueue()
  } catch (error) {
    toastError(toast, 'Не удалось принять кандидата', error, 'Не удалось принять кандидата')
  } finally {
    busyAction.value = ''
  }
}

async function rejectCandidateMatch(
  item: ProductNormalizationQueueItem,
  match: ProductNormalizationCandidateMatch,
): Promise<void> {
  busyAction.value = actionKey(item, `reject:${match.id}`)

  try {
    const decision = await rejectProductMatch(
      match.id,
      reasonByProductId[item.id] || 'Не тот товар',
    )
    toastSuccess(toast, 'Решение сохранено', decisionDescription(decision))
    await loadQueue()
  } catch (error) {
    toastError(toast, 'Не удалось отклонить кандидата', error, 'Не удалось отклонить кандидата')
  } finally {
    busyAction.value = ''
  }
}

function autoAcceptRequest(dryRun: boolean): ProductMatchAutoAcceptRequest {
  return {
    source: selectedSource.value || undefined,
    shopId: selectedShopId.value ? Number(selectedShopId.value) : undefined,
    categoryId: selectedCategoryId.value ? Number(selectedCategoryId.value) : undefined,
    q: searchQuery.value.trim() || undefined,
    minConfidence: 1,
    methods: ['exact_normalized_title'],
    limit: 250,
    dryRun,
    reason: 'Автопринято из inbox нормализации',
  }
}

async function previewAutoAcceptCandidates(): Promise<void> {
  isAutoAccepting.value = true
  autoAcceptPreview.value = null

  try {
    const response = await autoAcceptProductMatchCandidates(autoAcceptRequest(true))
    autoAcceptPreview.value = response
    if (response.would_accept === 0) {
      toastWarning(
        toast,
        'Нет безопасных автосвязей',
        'Для текущих фильтров нет точных однозначных кандидатов.',
      )
    } else {
      toastSuccess(
        toast,
        'Проверка завершена',
        `Можно принять автоматически: ${response.would_accept}`,
      )
    }
  } catch (error) {
    toastError(
      toast,
      'Не удалось проверить автосвязи',
      error,
      'Не удалось проверить автосвязи',
    )
  } finally {
    isAutoAccepting.value = false
  }
}

async function applyAutoAcceptCandidates(): Promise<void> {
  if (!autoAcceptPreview.value || autoAcceptPreview.value.would_accept === 0) {
    return
  }

  isAutoAccepting.value = true
  try {
    const response = await autoAcceptProductMatchCandidates(autoAcceptRequest(false))
    autoAcceptPreview.value = null
    toastSuccess(
      toast,
      'Кандидаты приняты',
      `Связано: ${response.accepted}. Новых кандидатов: ${response.followup_candidates_created}.`,
    )
    await loadQueue()
  } catch (error) {
    toastError(
      toast,
      'Не удалось применить автосвязи',
      error,
      'Не удалось применить автосвязи',
    )
  } finally {
    isAutoAccepting.value = false
  }
}

function clearAutoAcceptPreview(): void {
  autoAcceptPreview.value = null
}

function resetFilters(): void {
  clearAutoAcceptPreview()
  selectedSource.value = ''
  selectedShopId.value = ''
  selectedCategoryId.value = ''
  searchQuery.value = ''
  void loadQueue()
}

watch(selectedSource, () => {
  clearAutoAcceptPreview()
  if (selectedSource.value && selectedShopId.value) {
    const selectedShop = shops.value.find((shop) => String(shop.id) === selectedShopId.value)
    if (selectedShop && selectedShop.source !== selectedSource.value) {
      selectedShopId.value = ''
      return
    }
  }

  void loadQueue()
})

watch([selectedState, selectedShopId, selectedCategoryId], () => {
  clearAutoAcceptPreview()
  void loadQueue()
})

onMounted(() => {
  void loadQueue()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 2xl:flex-row 2xl:items-end 2xl:justify-between">
      <div>
        <p class="inline-flex items-center gap-2 text-sm font-medium text-amber-300">
          <Icon :icon="icons.listCheck" class="size-4" aria-hidden="true" />
          Нормализация товаров
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-white">Inbox исходных карточек</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
          Очередь решает, какие source products могут стать нормализованными товарами, а какие нужно оставить вне каталога.
        </p>
      </div>

      <div class="grid gap-3 sm:grid-cols-3 2xl:min-w-[640px]" data-testid="product-normalization-metrics">
        <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
          <p class="text-xs uppercase tracking-wide text-neutral-500">В текущем статусе</p>
          <p class="mt-2 text-2xl font-semibold text-white">{{ total }}</p>
        </div>
        <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
          <p class="text-xs uppercase tracking-wide text-neutral-500">В работе</p>
          <p class="mt-2 text-2xl font-semibold text-white">{{ workQueueCount }}</p>
        </div>
        <div class="rounded-lg border border-red-400/20 bg-red-400/10 p-4">
          <p class="text-xs uppercase tracking-wide text-red-200/80">Заблокировано</p>
          <p class="mt-2 text-2xl font-semibold text-red-100">{{ blockedCount }}</p>
        </div>
      </div>
    </div>

    <div class="flex gap-2 overflow-x-auto pb-1" aria-label="Статусы нормализации">
      <button
        v-for="status in statusOptions"
        :key="status.value"
        type="button"
        class="min-w-40 rounded-lg border px-4 py-3 text-left transition"
        :class="selectedState === status.value ? stateClass(status.value) : 'border-neutral-800 bg-neutral-900/40 text-neutral-400 hover:border-neutral-700 hover:text-white'"
        @click="selectedState = status.value"
      >
        <span class="block text-sm font-semibold">{{ status.label }}</span>
        <span class="mt-1 block text-xs opacity-75">{{ status.hint }}</span>
      </button>
    </div>

    <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4" data-testid="product-normalization-filters">
      <div class="grid gap-3 lg:grid-cols-[1.3fr_0.8fr_1fr_1fr_auto_auto]">
        <label class="relative block">
          <Icon :icon="icons.search" class="pointer-events-none absolute left-3 top-3 size-4 text-neutral-600" aria-hidden="true" />
          <input
            v-model="searchQuery"
            type="search"
            class="h-10 w-full rounded-md border border-neutral-800 bg-neutral-950 pl-9 pr-3 text-sm text-white outline-none transition placeholder:text-neutral-600 focus:border-amber-400"
            placeholder="Поиск по названию"
            aria-label="Поиск по названию исходного товара"
            @keyup.enter="clearAutoAcceptPreview(); loadQueue()"
          >
        </label>

        <select
          v-model="selectedSource"
          aria-label="Фильтр по источнику"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        >
          <option value="">Все источники</option>
          <option v-for="source in sourceOptions" :key="source" :value="source">
            {{ source }}
          </option>
        </select>

        <select
          v-model="selectedShopId"
          aria-label="Фильтр по магазину"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        >
          <option value="">Все магазины</option>
          <option v-for="shop in filteredShopOptions" :key="shop.id" :value="String(shop.id)">
            {{ shop.name }} · {{ shop.source }}
          </option>
        </select>

        <select
          v-model="selectedCategoryId"
          aria-label="Фильтр по категории"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        >
          <option value="">Все категории</option>
          <option v-for="category in categoryOptions" :key="category.id" :value="String(category.id)">
            {{ category.label }}
          </option>
        </select>

        <button
          type="button"
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-amber-300 px-4 text-sm font-semibold text-neutral-950 transition hover:bg-amber-200"
          @click="clearAutoAcceptPreview(); loadQueue()"
        >
          <Icon :icon="icons.filter" class="size-4" aria-hidden="true" />
          Найти
        </button>

        <button
          type="button"
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-neutral-800 px-4 text-sm font-semibold text-neutral-300 transition hover:border-neutral-700 hover:text-white"
          @click="resetFilters"
        >
          <Icon :icon="icons.x" class="size-4" aria-hidden="true" />
          Сбросить
        </button>
      </div>
    </div>

    <div
      v-if="canAutoAccept"
      class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4"
      data-testid="product-match-auto-accept"
    >
      <div class="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <p class="inline-flex items-center gap-2 text-sm font-semibold text-white">
            <Icon :icon="icons.check" class="size-4 text-emerald-300" aria-hidden="true" />
            Автопринятие точных кандидатов
          </p>
          <p class="mt-1 max-w-3xl text-sm leading-6 text-neutral-400">
            Проверяем текущие фильтры: 100% exact title, одна пара на карточку, совпадающая категория.
          </p>
        </div>

        <button
          type="button"
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-emerald-300 px-4 text-sm font-semibold text-neutral-950 transition hover:bg-emerald-200 disabled:cursor-wait disabled:opacity-60"
          :disabled="isAutoAccepting"
          @click="previewAutoAcceptCandidates"
        >
          <Icon :icon="icons.search" class="size-4" aria-hidden="true" />
          {{ isAutoAccepting ? 'Проверяем...' : 'Проверить точные' }}
        </button>
      </div>

      <div
        v-if="autoAcceptPreview"
        class="mt-4 grid gap-3 border-t border-neutral-800 pt-4 xl:grid-cols-[1fr_auto]"
      >
        <dl class="grid gap-3 sm:grid-cols-3">
          <div class="rounded-md border border-neutral-800 bg-neutral-950 p-3">
            <dt class="text-xs uppercase tracking-wide text-neutral-600">Кандидатов</dt>
            <dd class="mt-1 text-xl font-semibold text-white">{{ autoAcceptPreview.candidates_seen }}</dd>
          </div>
          <div class="rounded-md border border-emerald-400/30 bg-emerald-400/10 p-3">
            <dt class="text-xs uppercase tracking-wide text-emerald-200/80">Можно принять</dt>
            <dd class="mt-1 text-xl font-semibold text-emerald-100">{{ autoAcceptPreview.would_accept }}</dd>
          </div>
          <div class="rounded-md border border-neutral-800 bg-neutral-950 p-3">
            <dt class="text-xs uppercase tracking-wide text-neutral-600">Пропущено</dt>
            <dd class="mt-1 text-xl font-semibold text-neutral-200">{{ skippedAutoAcceptCount(autoAcceptPreview) }}</dd>
          </div>
        </dl>

        <div class="flex flex-col gap-2 sm:flex-row xl:items-start">
          <button
            type="button"
            class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-emerald-300 px-4 text-sm font-semibold text-neutral-950 transition hover:bg-emerald-200 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="isAutoAccepting || autoAcceptPreview.would_accept === 0"
            @click="applyAutoAcceptCandidates"
          >
            <Icon :icon="icons.check" class="size-4" aria-hidden="true" />
            {{ isAutoAccepting ? 'Применяем...' : `Принять ${autoAcceptPreview.would_accept}` }}
          </button>
          <button
            type="button"
            class="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-neutral-700 px-4 text-sm font-semibold text-neutral-300 transition hover:border-neutral-600 hover:text-white"
            @click="clearAutoAcceptPreview"
          >
            <Icon :icon="icons.x" class="size-4" aria-hidden="true" />
            Скрыть
          </button>
        </div>
      </div>
    </div>

    <div v-if="isLoading" class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-8 text-center text-sm text-neutral-500">
      <Icon :icon="icons.listCheck" class="mx-auto mb-3 size-6 text-neutral-600" aria-hidden="true" />
      Загружаем очередь нормализации...
    </div>

    <div
      v-else-if="items.length === 0"
      class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-8 text-center text-sm text-neutral-500"
    >
      <Icon :icon="icons.search" class="mx-auto mb-3 size-6 text-neutral-600" aria-hidden="true" />
      В статусе «{{ activeStatus.label }}» ничего нет.
    </div>

    <div v-else class="space-y-3">
      <article
        v-for="item in items"
        :key="item.id"
        class="rounded-lg border p-4"
        :class="item.state === 'ineligible' ? 'border-red-400/20 bg-red-950/20' : 'border-neutral-800 bg-neutral-900/40'"
        data-testid="product-normalization-row"
      >
        <div class="grid gap-4 xl:grid-cols-[1fr_280px]">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <span class="inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs" :class="stateClass(item.state)">
                <Icon :icon="item.state === 'ineligible' ? icons.shieldLock : icons.listCheck" class="size-3.5" aria-hidden="true" />
                {{ stateLabel(item.state) }}
              </span>
              <span class="text-xs text-neutral-500">#{{ item.id }} · {{ item.source }}</span>
              <span v-if="item.source_product_id" class="text-xs text-neutral-600">{{ item.source_product_id }}</span>
            </div>

            <RouterLink
              :to="`/products/${item.id}`"
              class="mt-3 block text-lg font-semibold text-white transition hover:text-amber-200"
            >
              {{ item.title }}
            </RouterLink>
            <p class="mt-1 text-sm text-neutral-500">{{ item.normalized_title }}</p>

            <div class="mt-4 grid gap-3 text-sm text-neutral-400 md:grid-cols-2 xl:grid-cols-4">
              <div>
                <p class="text-xs uppercase tracking-wide text-neutral-600">Магазин</p>
                <p class="mt-1 truncate text-neutral-200">{{ item.shop.name }}</p>
                <p class="text-xs text-neutral-600">{{ item.shop.source_id }}</p>
              </div>
              <div>
                <p class="text-xs uppercase tracking-wide text-neutral-600">Цена</p>
                <p class="mt-1 text-neutral-200">{{ formatPrice(item) }}</p>
              </div>
              <div>
                <p class="text-xs uppercase tracking-wide text-neutral-600">Категория</p>
                <p class="mt-1 text-neutral-200">{{ categoryLabel(item) }}</p>
                <p v-if="item.category_raw" class="text-xs text-neutral-600">{{ item.category_raw }}</p>
              </div>
              <div>
                <p class="text-xs uppercase tracking-wide text-neutral-600">Последнее наблюдение</p>
                <p class="mt-1 text-neutral-200">{{ formatDateTime(item.last_seen_at) }}</p>
              </div>
            </div>

            <div v-if="eligibilityReasons(item).length" class="mt-4 flex flex-wrap gap-2">
              <span
                v-for="reason in eligibilityReasons(item)"
                :key="reason"
                class="inline-flex items-center rounded-full border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-300"
              >
                {{ reason }}
              </span>
            </div>
          </div>

          <aside class="border-t border-neutral-800 pt-4 xl:border-l xl:border-t-0 xl:pl-4 xl:pt-0">
            <p class="inline-flex items-center gap-2 text-sm font-semibold text-white">
              <Icon :icon="icons.gitCompare" class="size-4 text-amber-300" aria-hidden="true" />
              Матчи
            </p>
            <dl class="mt-4 grid grid-cols-3 gap-3 text-center">
              <div>
                <dt class="text-xs text-neutral-600">Кандидаты</dt>
                <dd class="mt-1 text-lg font-semibold text-white">{{ item.match_summary.candidate_count }}</dd>
              </div>
              <div>
                <dt class="text-xs text-neutral-600">Отклонено</dt>
                <dd class="mt-1 text-lg font-semibold text-white">{{ item.match_summary.rejected_count }}</dd>
              </div>
              <div>
                <dt class="text-xs text-neutral-600">Принято</dt>
                <dd class="mt-1 text-lg font-semibold text-white">{{ item.match_summary.accepted_match_id ? 1 : 0 }}</dd>
              </div>
            </dl>

            <RouterLink
              v-if="item.match_summary.accepted_canonical_product_id && item.match_summary.accepted_canonical_title"
              :to="`/canonical-products/${item.match_summary.accepted_canonical_product_id}`"
              class="mt-4 block text-sm font-semibold text-neutral-200 transition hover:text-amber-200"
            >
              {{ item.match_summary.accepted_canonical_title }}
            </RouterLink>
            <p v-else-if="item.state === 'ineligible'" class="mt-4 text-sm text-red-100/80">
              Эта карточка не попадает в основной поток нормализации.
            </p>

            <div v-if="item.state !== 'ineligible' && item.state !== 'accepted'" class="mt-4 space-y-3">
              <textarea
                v-model="reasonByProductId[item.id]"
                class="min-h-20 w-full rounded-md border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm text-white outline-none transition placeholder:text-neutral-600 focus:border-amber-400"
                placeholder="Причина решения"
                aria-label="Причина решения по нормализации"
              />

              <button
                v-if="item.state === 'eligible_unmatched'"
                type="button"
                class="inline-flex w-full items-center justify-center gap-2 rounded-md bg-amber-300 px-3 py-2 text-sm font-semibold text-neutral-950 transition hover:bg-amber-200 disabled:cursor-wait disabled:opacity-60"
                :disabled="Boolean(busyAction)"
                @click="createCanonicalFromItem(item)"
              >
                <Icon :icon="icons.plus" class="size-4" aria-hidden="true" />
                {{ isBusy(item, 'create') ? 'Создаем...' : 'Создать товар' }}
              </button>

              <div v-if="item.candidate_matches.length" class="space-y-3 border-t border-neutral-800 pt-3">
                <div
                  v-for="match in item.candidate_matches"
                  :key="match.id"
                  class="space-y-2"
                >
                  <RouterLink
                    :to="`/canonical-products/${match.canonical_product_id}`"
                    class="block text-sm font-semibold text-white transition hover:text-amber-200"
                  >
                    {{ match.canonical_title }}
                  </RouterLink>
                  <p class="text-xs text-neutral-500">
                    {{ match.canonical_normalized_title }} · {{ confidencePercent(match.confidence) }} · {{ match.method }}
                  </p>
                  <div class="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      class="inline-flex items-center justify-center gap-2 rounded-md bg-emerald-300 px-3 py-2 text-sm font-semibold text-neutral-950 transition hover:bg-emerald-200 disabled:cursor-wait disabled:opacity-60"
                      :disabled="Boolean(busyAction)"
                      @click="acceptCandidateMatch(item, match)"
                    >
                      <Icon :icon="icons.check" class="size-4" aria-hidden="true" />
                      {{ isBusy(item, `accept:${match.id}`) ? 'Принимаем...' : 'Принять' }}
                    </button>
                    <button
                      type="button"
                      class="inline-flex items-center justify-center gap-2 rounded-md border border-neutral-700 px-3 py-2 text-sm font-semibold text-neutral-300 transition hover:border-red-300 hover:text-red-100 disabled:cursor-wait disabled:opacity-60"
                      :disabled="Boolean(busyAction)"
                      @click="rejectCandidateMatch(item, match)"
                    >
                      <Icon :icon="icons.x" class="size-4" aria-hidden="true" />
                      {{ isBusy(item, `reject:${match.id}`) ? 'Отклоняем...' : 'Отклонить' }}
                    </button>
                  </div>
                </div>
              </div>

              <div class="space-y-2 border-t border-neutral-800 pt-3">
                <label class="block text-xs uppercase tracking-wide text-neutral-600">
                  Связать с существующим
                </label>
                <div class="grid gap-2 sm:grid-cols-[1fr_auto] xl:grid-cols-1">
                  <input
                    v-model="canonicalSearchByProductId[item.id]"
                    type="search"
                    class="h-10 rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition placeholder:text-neutral-600 focus:border-amber-400"
                    :placeholder="item.normalized_title"
                    aria-label="Поиск нормализованного товара"
                    @keyup.enter="searchCanonicalProductsForItem(item)"
                  >
                  <button
                    type="button"
                    class="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-neutral-700 px-3 text-sm font-semibold text-neutral-300 transition hover:border-amber-300 hover:text-white disabled:cursor-wait disabled:opacity-60"
                    :disabled="Boolean(busyAction)"
                    @click="searchCanonicalProductsForItem(item)"
                  >
                    <Icon :icon="icons.search" class="size-4" aria-hidden="true" />
                    {{ isBusy(item, 'search') ? 'Ищем...' : 'Найти' }}
                  </button>
                </div>

                <select
                  v-if="canonicalResultsByProductId[item.id]?.length"
                  v-model="selectedCanonicalByProductId[item.id]"
                  class="h-10 w-full rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition focus:border-amber-400"
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
                  class="inline-flex w-full items-center justify-center gap-2 rounded-md bg-amber-300 px-3 py-2 text-sm font-semibold text-neutral-950 transition hover:bg-amber-200 disabled:cursor-wait disabled:opacity-60"
                  :disabled="Boolean(busyAction) || !selectedCanonicalByProductId[item.id]"
                  @click="linkCanonicalProduct(item)"
                >
                  <Icon :icon="icons.link" class="size-4" aria-hidden="true" />
                  {{ isBusy(item, 'link') ? 'Связываем...' : 'Связать' }}
                </button>
              </div>
            </div>
          </aside>
        </div>
      </article>
    </div>
  </section>
</template>
