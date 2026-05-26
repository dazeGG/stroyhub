<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import {
  fetchCatalogQualityFindings,
  fetchCatalogWorkflowDashboard,
  fetchCategoryQuality,
  fetchScrapeHealth,
  fetchShopSourceCandidates,
  fetchShops,
  type CatalogQualityFinding,
  type CatalogQualityFindingsResponse,
  type CatalogWorkflowDashboardCount,
  type CatalogWorkflowQueueName,
  type CategoryQualityResponse,
  type RecentScrapeRun,
  type ScrapeHealthResponse,
  type ShopListItem,
  type ShopSourceCandidateListResponse,
} from '../lib/api'
import { icons } from '../lib/icons'

interface QueueMeta {
  queue: CatalogWorkflowQueueName
  label: string
  detail: string
  to: string
  icon: typeof icons.check
  tone: string
}

interface AttentionMetric {
  label: string
  value: number
  detail: string
  to: string
  icon: typeof icons.check
  tone: string
}

const queueMeta: QueueMeta[] = [
  {
    queue: 'auto_acceptable',
    label: 'Можно принять',
    detail: 'готово к пакетному решению',
    to: '/workflows/queues/auto_acceptable',
    icon: icons.check,
    tone: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100',
  },
  {
    queue: 'review_needed',
    label: 'Проверка',
    detail: 'спорные категории или нормализация',
    to: '/workflows/queues/review_needed',
    icon: icons.listCheck,
    tone: 'border-amber-400/30 bg-amber-400/10 text-amber-100',
  },
  {
    queue: 'possible_duplicates',
    label: 'Похожие товары',
    detail: 'есть кандидаты на связь',
    to: '/workflows/queues/possible_duplicates',
    icon: icons.gitCompare,
    tone: 'border-sky-400/30 bg-sky-400/10 text-sky-100',
  },
  {
    queue: 'data_problems',
    label: 'Проблемы данных',
    detail: 'не товар, ошибка обработки или плохие данные',
    to: '/workflows/queues/data_problems',
    icon: icons.alertTriangle,
    tone: 'border-red-400/30 bg-red-400/10 text-red-100',
  },
  {
    queue: 'normalized_items',
    label: 'В каталоге',
    detail: 'принятые карточки',
    to: '/workflows/queues/normalized_items',
    icon: icons.tags,
    tone: 'border-neutral-700 bg-neutral-900/70 text-neutral-100',
  },
]

const qualityCodeLabels: Record<string, string> = {
  accepted_attribute_conflict: 'Конфликт признаков',
  duplicate_normalized_product: 'Дубли в каталоге',
  low_confidence_category: 'Слабая категория',
  missing_critical_attributes: 'Нет важных признаков',
  missing_price_snapshot: 'Нет цены',
  shop_never_scraped: 'Источник не загружался',
  stale_price: 'Устарела цена',
  stale_shop: 'Устарел источник',
  uncategorized_product: 'Нет категории',
}

const qualityCodeDetails: Record<string, string> = {
  accepted_attribute_conflict: 'Связанные карточки расходятся по важным признакам.',
  duplicate_normalized_product: 'Несколько товаров в каталоге совпадают по названию и категории.',
  low_confidence_category: 'Категория определена с низкой уверенностью.',
  missing_critical_attributes: 'Не хватает защищенных признаков для уверенного показа.',
  missing_price_snapshot: 'Нет актуальной цены.',
  shop_never_scraped: 'Источник еще не загружался.',
  stale_price: 'Цена давно не обновлялась.',
  stale_shop: 'Источник давно не обновлялся.',
  uncategorized_product: 'Карточка еще не попала в категорию.',
}

const counts = ref<CatalogWorkflowDashboardCount[]>([])
const scrapeHealth = ref<ScrapeHealthResponse | null>(null)
const shops = ref<ShopListItem[]>([])
const candidates = ref<ShopSourceCandidateListResponse | null>(null)
const categoryQuality = ref<CategoryQualityResponse | null>(null)
const catalogQuality = ref<CatalogQualityFindingsResponse | null>(null)
const isLoading = ref(false)
const errorMessage = ref('')

const countByQueue = computed(() => {
  return Object.fromEntries(counts.value.map((item) => [item.queue, item.count])) as Record<
    CatalogWorkflowQueueName,
    number | undefined
  >
})

const activeWorkCount = computed(() => {
  return queueMeta
    .filter((item) => item.queue !== 'normalized_items')
    .reduce((sum, item) => sum + (countByQueue.value[item.queue] ?? 0), 0)
})

const failedScrapeCount = computed(() => {
  return scrapeHealth.value?.status_counts
    .filter((item) => item.status === 'failed' || item.status === 'partial')
    .reduce((sum, item) => sum + item.count, 0) ?? 0
})

const pipelineFailedCount = computed(() => {
  return scrapeHealth.value?.catalog_pipeline_status_counts
    .filter((item) => item.status === 'failed')
    .reduce((sum, item) => sum + item.count, 0) ?? 0
})

const staleSourceCount = computed(() => {
  const now = Date.now()
  return shops.value.filter((shop) => {
    if (shop.scrape_status === 'disabled' || shop.scrape_status === 'running') {
      return false
    }
    if (!shop.last_scraped_at) {
      return true
    }
    return Boolean(shop.next_scrape_at && Date.parse(shop.next_scrape_at) <= now)
  }).length
})

const sourceFailureCount = computed(() => {
  return shops.value.filter((shop) => shop.scrape_status === 'failed' || shop.error_count > 0).length
})

const sourceAttentionCount = computed(() => {
  const now = Date.now()
  return shops.value.filter((shop) => {
    const stale = !shop.last_scraped_at || Boolean(shop.next_scrape_at && Date.parse(shop.next_scrape_at) <= now)
    const failed = shop.scrape_status === 'failed' || shop.error_count > 0

    return shop.scrape_status !== 'disabled' && shop.scrape_status !== 'running' && (stale || failed)
  }).length
})

const pendingCandidateCount = computed(() => candidates.value?.items.length ?? 0)
const uncategorizedCount = computed(() => categoryQuality.value?.uncategorized_products ?? 0)
const qualityBlockerCount = computed(() => catalogQuality.value?.summary.blockers ?? 0)
const qualityWarningCount = computed(() => catalogQuality.value?.summary.warnings ?? 0)

const attentionMetrics = computed<AttentionMetric[]>(() => [
  {
    label: 'Принять',
    value: countByQueue.value.auto_acceptable ?? 0,
    detail: 'безопасные решения',
    to: '/workflows/queues/auto_acceptable',
    icon: icons.check,
    tone: 'border-emerald-400/30 text-emerald-100',
  },
  {
    label: 'Проверить',
    value: countByQueue.value.review_needed ?? 0,
    detail: 'спорные карточки',
    to: '/workflows/queues/review_needed',
    icon: icons.listCheck,
    tone: 'border-amber-400/30 text-amber-100',
  },
  {
    label: 'Блокеры',
    value: qualityBlockerCount.value,
    detail: 'качество каталога',
    to: '/workflows/queues/normalized_items',
    icon: icons.alertTriangle,
    tone: 'border-red-400/30 text-red-100',
  },
  {
    label: 'Источники',
    value: sourceAttentionCount.value,
    detail: 'просрочены или с ошибками',
    to: '/shops',
    icon: icons.buildingStore,
    tone: 'border-sky-400/30 text-sky-100',
  },
  {
    label: 'Новые источники',
    value: pendingCandidateCount.value,
    detail: 'ждут решения',
    to: '/shops/candidates',
    icon: icons.databaseImport,
    tone: 'border-violet-400/30 text-violet-100',
  },
  {
    label: 'Без категории',
    value: uncategorizedCount.value,
    detail: 'нужна категоризация',
    to: '/categories/quality',
    icon: icons.category,
    tone: 'border-orange-400/30 text-orange-100',
  },
])

const recentProblemRuns = computed(() => {
  return (scrapeHealth.value?.recent_runs ?? [])
    .filter((run) => run.status === 'failed' || run.status === 'partial')
    .slice(0, 4)
})

const topQualityFindings = computed(() => catalogQuality.value?.findings.items.slice(0, 5) ?? [])

async function loadDashboard(): Promise<void> {
  isLoading.value = true
  errorMessage.value = ''

  try {
    const [
      workflowResponse,
      scrapeResponse,
      shopResponse,
      candidateResponse,
      categoryResponse,
      qualityResponse,
    ] = await Promise.all([
      fetchCatalogWorkflowDashboard(),
      fetchScrapeHealth({ limit: 8 }),
      fetchShops(),
      fetchShopSourceCandidates({ status: 'pending' }),
      fetchCategoryQuality({ limitGroups: 5, titlesPerGroup: 3 }),
      fetchCatalogQualityFindings({ limit: 5 }),
    ])
    counts.value = workflowResponse.counts
    scrapeHealth.value = scrapeResponse
    shops.value = shopResponse.items
    candidates.value = candidateResponse
    categoryQuality.value = categoryResponse
    catalogQuality.value = qualityResponse
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Неизвестная ошибка'
  } finally {
    isLoading.value = false
  }
}

function findingLabel(finding: CatalogQualityFinding): string {
  return qualityCodeLabels[finding.code] ?? finding.code
}

function findingDetail(finding: CatalogQualityFinding): string {
  return qualityCodeDetails[finding.code] ?? finding.reason
}

function findingLink(finding: CatalogQualityFinding): string {
  if (finding.source_product_id !== null) {
    return `/products/${finding.source_product_id}`
  }
  if (finding.canonical_product_id !== null) {
    return `/canonical-products/${finding.canonical_product_id}`
  }
  return '/workflows/queues/normalized_items'
}

function formatDate(value: string | null): string {
  if (!value) {
    return 'не было'
  }
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function runShopLabel(run: RecentScrapeRun): string {
  return run.shop_id === null ? run.source : `${run.source} / #${run.shop_id}`
}

onMounted(() => {
  void loadDashboard()
})
</script>

<template>
  <section class="space-y-7">
    <div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
      <div>
        <p class="inline-flex items-center gap-2 text-sm font-medium text-amber-300">
          <Icon :icon="icons.layoutDashboard" class="size-4" aria-hidden="true" />
          Качество каталога
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-white">Что требует внимания</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
          Сводка по очередям, источникам и проверкам, которые влияют на готовность публичного каталога.
        </p>
      </div>

      <div class="flex flex-wrap gap-2">
        <button
          type="button"
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-neutral-700 px-4 text-sm font-semibold text-neutral-100 transition hover:border-neutral-500"
          @click="loadDashboard"
        >
          <Icon :icon="icons.refresh" class="size-4" aria-hidden="true" />
          Обновить
        </button>
        <RouterLink
          to="/workflows/queues/auto_acceptable"
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-amber-300 px-4 text-sm font-semibold text-neutral-950 transition hover:bg-amber-200"
        >
          <Icon :icon="icons.check" class="size-4" aria-hidden="true" />
          Открыть очередь
        </RouterLink>
      </div>
    </div>

    <div
      v-if="errorMessage"
      class="rounded-lg border border-red-400/30 bg-red-400/10 p-4 text-sm text-red-100"
    >
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p>{{ errorMessage }}</p>
        <button
          type="button"
          class="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-red-300/40 px-3 text-sm font-semibold text-red-50 transition hover:border-red-200"
          @click="loadDashboard"
        >
          <Icon :icon="icons.refresh" class="size-4" aria-hidden="true" />
          Повторить
        </button>
      </div>
    </div>

    <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
      <RouterLink
        v-for="metric in attentionMetrics"
        :key="metric.label"
        :to="metric.to"
        class="group rounded-lg border bg-neutral-900/40 p-4 transition hover:-translate-y-0.5 hover:border-amber-300/50"
        :class="metric.tone"
      >
        <div class="flex items-center justify-between gap-3">
          <Icon :icon="metric.icon" class="size-5 text-current" aria-hidden="true" />
          <span class="text-2xl font-semibold text-white">
            {{ isLoading ? '...' : metric.value }}
          </span>
        </div>
        <p class="mt-4 text-sm font-semibold text-neutral-100">{{ metric.label }}</p>
        <p class="mt-1 text-xs text-neutral-400">{{ metric.detail }}</p>
      </RouterLink>
    </div>

    <div class="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
      <section class="space-y-3">
        <div class="flex items-center justify-between gap-3">
          <div>
            <h3 class="text-base font-semibold text-white">Очереди решений</h3>
            <p class="mt-1 text-sm text-neutral-500">{{ activeWorkCount }} карточек в работе</p>
          </div>
          <RouterLink
            to="/workflows/queues/review_needed"
            class="text-sm font-semibold text-amber-300 hover:text-amber-200"
          >
            Проверка
          </RouterLink>
        </div>

        <div class="grid gap-3 lg:grid-cols-5">
          <RouterLink
            v-for="item in queueMeta"
            :key="item.queue"
            :to="item.to"
            class="rounded-lg border p-4 transition hover:-translate-y-0.5 hover:border-amber-300/50"
            :class="item.tone"
          >
            <div class="flex items-center justify-between gap-3">
              <Icon :icon="item.icon" class="size-5" aria-hidden="true" />
              <span class="text-2xl font-semibold">
                {{ isLoading ? '...' : (countByQueue[item.queue] ?? 0) }}
              </span>
            </div>
            <p class="mt-4 text-sm font-semibold">{{ item.label }}</p>
            <p class="mt-1 text-xs opacity-75">{{ item.detail }}</p>
          </RouterLink>
        </div>
      </section>

      <section class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <div class="flex items-start justify-between gap-3">
          <div>
            <h3 class="text-base font-semibold text-white">Источники</h3>
            <p class="mt-1 text-sm text-neutral-500">свежесть данных и загрузки</p>
          </div>
          <RouterLink to="/scrapes" class="text-sm font-semibold text-amber-300 hover:text-amber-200">
            Загрузки
          </RouterLink>
        </div>

        <dl class="mt-5 grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt class="text-neutral-500">Просрочены</dt>
            <dd class="mt-1 text-2xl font-semibold text-white">{{ isLoading ? '...' : staleSourceCount }}</dd>
          </div>
          <div>
            <dt class="text-neutral-500">Источники с ошибкой</dt>
            <dd class="mt-1 text-2xl font-semibold text-white">{{ isLoading ? '...' : sourceFailureCount }}</dd>
          </div>
          <div>
            <dt class="text-neutral-500">Запуски с ошибкой</dt>
            <dd class="mt-1 text-2xl font-semibold text-white">{{ isLoading ? '...' : failedScrapeCount }}</dd>
          </div>
          <div>
            <dt class="text-neutral-500">Ошибка обработки</dt>
            <dd class="mt-1 text-2xl font-semibold text-white">{{ isLoading ? '...' : pipelineFailedCount }}</dd>
          </div>
          <div>
            <dt class="text-neutral-500">Новые источники</dt>
            <dd class="mt-1 text-2xl font-semibold text-white">{{ isLoading ? '...' : pendingCandidateCount }}</dd>
          </div>
        </dl>

        <div v-if="recentProblemRuns.length" class="mt-5 space-y-2">
          <RouterLink
            v-for="run in recentProblemRuns"
            :key="run.id"
            to="/scrapes"
            class="flex items-center justify-between gap-3 rounded-md border border-neutral-800 px-3 py-2 text-sm transition hover:border-neutral-600"
          >
            <span class="min-w-0 truncate text-neutral-200">{{ runShopLabel(run) }}</span>
            <span class="shrink-0 text-neutral-500">{{ formatDate(run.started_at) }}</span>
          </RouterLink>
        </div>
        <p v-else class="mt-5 text-sm text-neutral-500">Свежих ошибок загрузки нет.</p>
      </section>
    </div>

    <div class="grid gap-4 xl:grid-cols-2">
      <section class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <div class="flex items-start justify-between gap-3">
          <div>
            <h3 class="text-base font-semibold text-white">Проверки каталога</h3>
            <p class="mt-1 text-sm text-neutral-500">
              {{ qualityBlockerCount }} блокеров, {{ qualityWarningCount }} предупреждений
            </p>
          </div>
          <RouterLink
            to="/workflows/queues/normalized_items"
            class="text-sm font-semibold text-amber-300 hover:text-amber-200"
          >
            Каталог
          </RouterLink>
        </div>

        <div v-if="topQualityFindings.length" class="mt-5 space-y-2">
          <RouterLink
            v-for="finding in topQualityFindings"
            :key="`${finding.code}-${finding.source_product_id}-${finding.canonical_product_id}`"
            :to="findingLink(finding)"
            class="block rounded-md border border-neutral-800 px-3 py-3 transition hover:border-neutral-600"
          >
            <div class="flex items-center justify-between gap-3">
              <p class="text-sm font-semibold text-neutral-100">{{ findingLabel(finding) }}</p>
              <span
                class="rounded px-2 py-1 text-xs font-semibold"
                :class="finding.severity === 'blocker' ? 'bg-red-400/10 text-red-200' : 'bg-amber-400/10 text-amber-200'"
              >
                {{ finding.severity === 'blocker' ? 'Блокер' : 'Риск' }}
              </span>
            </div>
            <p class="mt-2 line-clamp-2 text-sm text-neutral-400">{{ findingDetail(finding) }}</p>
          </RouterLink>
        </div>
        <p v-else class="mt-5 text-sm text-neutral-500">Активных замечаний нет.</p>
      </section>

      <section class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <div class="flex items-start justify-between gap-3">
          <div>
            <h3 class="text-base font-semibold text-white">Категоризация</h3>
            <p class="mt-1 text-sm text-neutral-500">
              покрытие {{ categoryQuality?.coverage_pct ?? '0.00' }}%
            </p>
          </div>
          <RouterLink to="/categories/quality" class="text-sm font-semibold text-amber-300 hover:text-amber-200">
            Категории
          </RouterLink>
        </div>

        <div class="mt-5 grid grid-cols-3 gap-3 text-sm">
          <div>
            <p class="text-neutral-500">Всего</p>
            <p class="mt-1 text-2xl font-semibold text-white">{{ categoryQuality?.total_products ?? 0 }}</p>
          </div>
          <div>
            <p class="text-neutral-500">Готово</p>
            <p class="mt-1 text-2xl font-semibold text-white">{{ categoryQuality?.categorized_products ?? 0 }}</p>
          </div>
          <div>
            <p class="text-neutral-500">Без категории</p>
            <p class="mt-1 text-2xl font-semibold text-white">{{ uncategorizedCount }}</p>
          </div>
        </div>

        <div v-if="categoryQuality?.groups.length" class="mt-5 space-y-2">
          <RouterLink
            v-for="group in categoryQuality.groups.slice(0, 4)"
            :key="`${group.source}-${group.shop_id}-${group.category_raw}`"
            to="/categories/quality"
            class="flex items-center justify-between gap-3 rounded-md border border-neutral-800 px-3 py-2 text-sm transition hover:border-neutral-600"
          >
            <span class="min-w-0 truncate text-neutral-200">
              {{ group.category_raw || 'Без исходной категории' }}
            </span>
            <span class="shrink-0 text-neutral-500">{{ group.count }}</span>
          </RouterLink>
        </div>
        <p v-else class="mt-5 text-sm text-neutral-500">Очередь категоризации пуста.</p>
      </section>
    </div>

    <div
      v-if="!isLoading && !errorMessage && activeWorkCount === 0 && qualityBlockerCount === 0"
      class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-6 text-sm text-neutral-400"
    >
      Активных очередей и блокеров нет.
    </div>
  </section>
</template>
