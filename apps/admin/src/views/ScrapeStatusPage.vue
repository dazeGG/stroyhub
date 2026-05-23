<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { computed, onMounted, ref, watch } from 'vue'

import {
  fetchScrapeHealth,
  fetchShops,
  retryShopScrape,
  type RecentScrapeRun,
  type ScrapeStatusCount,
  type ShopListItem,
} from '../lib/api'
import { icons } from '../lib/icons'

const selectedSource = ref('')
const selectedStatus = ref('')
const shops = ref<ShopListItem[]>([])
const allShops = ref<ShopListItem[]>([])
const statusCounts = ref<ScrapeStatusCount[]>([])
const recentRuns = ref<RecentScrapeRun[]>([])
const isLoading = ref(false)
const errorMessage = ref('')
const saveMessage = ref('')
const retryingShopId = ref<number | null>(null)

let dashboardRequest: AbortController | null = null

const sourceOptions = computed(() => {
  return Array.from(new Set(allShops.value.map((shop) => shop.source))).sort()
})

const statusOptions = computed(() => {
  const shopStatuses = allShops.value.map((shop) => shop.scrape_status)
  const runStatuses = statusCounts.value.map((item) => item.status)
  return Array.from(new Set([...shopStatuses, ...runStatuses])).sort()
})

const statusCountByName = computed(() => {
  return new Map(statusCounts.value.map((item) => [item.status, item.count]))
})

const failedOrPartialRuns = computed(() => {
  return (statusCountByName.value.get('failed') || 0) + (statusCountByName.value.get('partial') || 0)
})

const dueShops = computed(() => {
  const now = Date.now()
  return shops.value.filter((shop) => {
    if (!shop.next_scrape_at || shop.scrape_status === 'disabled') {
      return false
    }

    return new Date(shop.next_scrape_at).getTime() <= now
  }).length
})

const mostRecentRun = computed(() => recentRuns.value[0] || null)

function formatDateTime(value: string | null): string {
  if (!value) {
    return '-'
  }

  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function formatDuration(run: RecentScrapeRun): string {
  if (!run.finished_at) {
    return 'в процессе'
  }

  const seconds = Math.max(
    0,
    Math.round((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000),
  )
  if (seconds < 60) {
    return `${seconds} c`
  }

  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest ? `${minutes} мин ${rest} c` : `${minutes} мин`
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    disabled: 'Отключен',
    failed: 'Ошибка',
    new: 'Новый',
    partial: 'Частично',
    running: 'В процессе',
    success: 'Успешно',
  }

  return labels[status] || status
}

function statusClass(status: string): string {
  if (status === 'failed') {
    return 'border-red-400/30 bg-red-400/10 text-red-200'
  }
  if (status === 'partial') {
    return 'border-amber-400/30 bg-amber-400/10 text-amber-200'
  }
  if (status === 'success') {
    return 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'
  }
  if (status === 'disabled') {
    return 'border-neutral-700 bg-neutral-900 text-neutral-500'
  }

  return 'border-neutral-700 bg-neutral-900 text-neutral-300'
}

function canRetryShop(shop: ShopListItem): boolean {
  return ['failed', 'partial'].includes(shop.scrape_status)
}

async function loadDashboard(): Promise<void> {
  dashboardRequest?.abort()
  const request = new AbortController()
  dashboardRequest = request
  isLoading.value = true
  errorMessage.value = ''

  try {
    const [allShopResponse, shopResponse, healthResponse] = await Promise.all([
      fetchShops({}, request.signal),
      fetchShops(
        {
          source: selectedSource.value,
          status: selectedStatus.value,
        },
        request.signal,
      ),
      fetchScrapeHealth(
        {
          source: selectedSource.value,
          status: selectedStatus.value,
          limit: 20,
        },
        request.signal,
      ),
    ])
    allShops.value = allShopResponse.items
    shops.value = shopResponse.items
    statusCounts.value = healthResponse.status_counts
    recentRuns.value = healthResponse.recent_runs
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }

    errorMessage.value = error instanceof Error ? error.message : 'Не удалось загрузить статус скрейпов'
    shops.value = []
    statusCounts.value = []
    recentRuns.value = []
  } finally {
    if (dashboardRequest === request) {
      isLoading.value = false
    }
  }
}

async function retryScrape(shop: ShopListItem): Promise<void> {
  retryingShopId.value = shop.id
  errorMessage.value = ''
  saveMessage.value = ''

  try {
    await retryShopScrape(shop.id)
    saveMessage.value = `${shop.name}: scrape поставлен в очередь`
    await loadDashboard()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Не удалось перезапустить scrape'
  } finally {
    retryingShopId.value = null
  }
}

watch([selectedSource, selectedStatus], () => {
  void loadDashboard()
})

onMounted(() => {
  void loadDashboard()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 2xl:flex-row 2xl:items-end 2xl:justify-between">
      <div>
        <p class="inline-flex items-center gap-2 text-sm font-medium text-amber-300">
          <Icon :icon="icons.activity" class="size-4" aria-hidden="true" />
          Статус скрейпов
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-white">Здоровье источников</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
          Смотрим последние запуски, упавшие магазины, устаревшие источники и расписание следующих запусков.
        </p>
      </div>

      <div
        class="grid gap-3 sm:grid-cols-2 2xl:min-w-[520px]"
        data-testid="scrape-dashboard-filters"
      >
        <select
          v-model="selectedSource"
          aria-label="Фильтр скрейпов по источнику"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        >
          <option value="">Все источники</option>
          <option v-for="source in sourceOptions" :key="source" :value="source">
            {{ source }}
          </option>
        </select>
        <select
          v-model="selectedStatus"
          aria-label="Фильтр скрейпов по статусу"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        >
          <option value="">Все статусы</option>
          <option v-for="status in statusOptions" :key="status" :value="status">
            {{ statusLabel(status) }}
          </option>
        </select>
      </div>
    </div>

    <div
      v-if="errorMessage"
      class="rounded-lg border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-100"
    >
      Не удалось загрузить статус скрейпов: {{ errorMessage }}
    </div>
    <div
      v-if="saveMessage"
      class="rounded-lg border border-emerald-400/30 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100"
    >
      {{ saveMessage }}
    </div>

    <div class="grid gap-4 md:grid-cols-4">
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="inline-flex items-center gap-2 text-sm text-neutral-500">
          <Icon :icon="icons.buildingStore" class="size-4" aria-hidden="true" />
          Магазины
        </p>
        <p class="mt-3 text-3xl font-semibold text-white">{{ shops.length }}</p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="inline-flex items-center gap-2 text-sm text-neutral-500">
          <Icon :icon="icons.alertTriangle" class="size-4" aria-hidden="true" />
          Failed / partial
        </p>
        <p class="mt-3 text-3xl font-semibold" :class="failedOrPartialRuns > 0 ? 'text-red-200' : 'text-white'">
          {{ failedOrPartialRuns }}
        </p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="inline-flex items-center gap-2 text-sm text-neutral-500">
          <Icon :icon="icons.calendarDue" class="size-4" aria-hidden="true" />
          Due now
        </p>
        <p class="mt-3 text-3xl font-semibold" :class="dueShops > 0 ? 'text-amber-200' : 'text-white'">
          {{ dueShops }}
        </p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="inline-flex items-center gap-2 text-sm text-neutral-500">
          <Icon :icon="icons.clock" class="size-4" aria-hidden="true" />
          Последний запуск
        </p>
        <p class="mt-3 text-lg font-semibold text-white">
          {{ mostRecentRun ? formatDateTime(mostRecentRun.started_at) : '-' }}
        </p>
      </div>
    </div>

    <div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.9fr)]">
      <div class="overflow-x-auto rounded-lg border border-neutral-800 bg-neutral-900/40">
        <div
          class="grid min-w-[1020px] grid-cols-[minmax(220px,1.5fr)_110px_130px_170px_170px_minmax(150px,1fr)_150px] border-b border-neutral-800 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neutral-500"
        >
          <span>Магазин</span>
          <span>Источник</span>
          <span>Статус</span>
          <span>Последний scrape</span>
          <span>Следующий scrape</span>
          <span>Адрес</span>
          <span>Действие</span>
        </div>

        <div v-if="isLoading" class="min-w-[1020px] px-4 py-14 text-center text-sm text-neutral-500">
          <Icon :icon="icons.activity" class="mx-auto mb-3 size-6 text-neutral-600" aria-hidden="true" />
          Загружаем магазины...
        </div>

        <div
          v-else-if="shops.length === 0"
          class="min-w-[1020px] px-4 py-14 text-center text-sm text-neutral-500"
        >
          <Icon :icon="icons.search" class="mx-auto mb-3 size-6 text-neutral-600" aria-hidden="true" />
          По этим фильтрам магазинов не найдено.
        </div>

        <div v-else class="min-w-[1020px] divide-y divide-neutral-800">
          <div
            v-for="shop in shops"
            :key="shop.id"
            class="grid grid-cols-[minmax(220px,1.5fr)_110px_130px_170px_170px_minmax(150px,1fr)_150px] px-4 py-4 text-sm"
            data-testid="scrape-shop-row"
          >
            <div class="min-w-0 pr-5">
              <p class="truncate font-medium text-white" :title="shop.name">{{ shop.name }}</p>
              <p class="mt-1 truncate text-xs text-neutral-500" :title="shop.source_id">{{ shop.source_id }}</p>
            </div>
            <div class="text-neutral-300">{{ shop.source }}</div>
            <div>
              <span class="rounded-full border px-2 py-1 text-xs" :class="statusClass(shop.scrape_status)">
                {{ statusLabel(shop.scrape_status) }}
              </span>
            </div>
            <div class="text-neutral-400">{{ formatDateTime(shop.last_scraped_at) }}</div>
            <div class="text-neutral-400">{{ formatDateTime(shop.next_scrape_at) }}</div>
            <div class="min-w-0 pr-5 text-neutral-500">
              <p class="truncate" :title="shop.address || '-'">{{ shop.address || '-' }}</p>
            </div>
            <div>
              <button
                v-if="canRetryShop(shop)"
                type="button"
                class="inline-flex h-8 items-center justify-center gap-2 rounded-md border border-amber-400/40 bg-amber-400/10 px-3 text-xs font-medium text-amber-100 transition hover:border-amber-300 hover:bg-amber-300/15 hover:text-amber-50 disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="retryingShopId === shop.id"
                @click="retryScrape(shop)"
              >
                <Icon :icon="icons.refresh" class="size-3.5" aria-hidden="true" />
                {{ retryingShopId === shop.id ? 'Ставим...' : 'Перезапуск' }}
              </button>
              <span v-else class="text-xs text-neutral-600">-</span>
            </div>
          </div>
        </div>
      </div>

      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40">
        <div class="flex items-center gap-2 border-b border-neutral-800 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neutral-500">
          <Icon :icon="icons.timeline" class="size-4" aria-hidden="true" />
          Recent runs
        </div>

        <div v-if="isLoading" class="px-4 py-14 text-center text-sm text-neutral-500">
          <Icon :icon="icons.timeline" class="mx-auto mb-3 size-6 text-neutral-600" aria-hidden="true" />
          Загружаем запуски...
        </div>

        <div v-else-if="recentRuns.length === 0" class="px-4 py-14 text-center text-sm text-neutral-500">
          <Icon :icon="icons.search" class="mx-auto mb-3 size-6 text-neutral-600" aria-hidden="true" />
          Запусков по этим фильтрам нет.
        </div>

        <div v-else class="divide-y divide-neutral-800">
          <div
            v-for="run in recentRuns"
            :key="run.id"
            class="p-4 text-sm"
            data-testid="scrape-run-row"
          >
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p class="font-medium text-white">#{{ run.id }} · {{ run.source }}</p>
                <p class="mt-1 text-xs text-neutral-500">
                  shop {{ run.shop_id || '-' }} · {{ formatDuration(run) }}
                </p>
              </div>
              <span class="rounded-full border px-2 py-1 text-xs" :class="statusClass(run.status)">
                {{ statusLabel(run.status) }}
              </span>
            </div>
            <div class="mt-3 grid gap-2 text-xs text-neutral-500 sm:grid-cols-2">
              <p>started: {{ formatDateTime(run.started_at) }}</p>
              <p>finished: {{ formatDateTime(run.finished_at) }}</p>
              <p>seen: {{ run.items_seen }}</p>
              <p>saved: {{ run.items_saved }}</p>
            </div>
            <p v-if="run.error" class="mt-3 rounded-md bg-red-400/10 px-3 py-2 text-xs text-red-100">
              {{ run.error }}
            </p>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
