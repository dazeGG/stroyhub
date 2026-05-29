<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { useToast } from '@nuxt/ui/composables'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  fetchScrapeHealth,
  fetchShops,
  retryShopScrape,
  type RecentScrapeRun,
  type ScrapeStatusCount,
  type ShopListItem,
} from '../lib/api'
import { icons } from '../lib/icons'
import { messageFromError, toastError, toastSuccess } from '../lib/notifications'

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
const isRecentRunsModalOpen = ref(false)
const toast = useToast()

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
    return 'border-admin-danger-border bg-admin-danger-soft text-admin-danger'
  }
  if (status === 'partial') {
    return 'border-admin-border-strong bg-admin-surface-muted text-admin-link'
  }
  if (status === 'success') {
    return 'border-admin-success-border bg-admin-success-soft text-admin-success'
  }
  if (status === 'disabled') {
    return 'border-admin-border-strong bg-admin-surface-muted text-admin-text-faint'
  }

  return 'border-admin-border-strong bg-admin-surface-muted text-admin-text-muted'
}

function canRetryShop(shop: ShopListItem): boolean {
  return ['failed', 'partial'].includes(shop.scrape_status) || shop.enqueue_failed !== null
}

function enqueueFailureTitle(shop: ShopListItem): string {
  if (!shop.enqueue_failed) {
    return ''
  }

  return `${shop.enqueue_failed.operation}: ${shop.enqueue_failed.reason}`
}

function openRecentRunsModal(): void {
  isRecentRunsModalOpen.value = true
}

function closeRecentRunsModal(): void {
  isRecentRunsModalOpen.value = false
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && isRecentRunsModalOpen.value) {
    closeRecentRunsModal()
  }
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
          includeCatalogPipeline: false,
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

    errorMessage.value = messageFromError(error, 'Не удалось загрузить статус скрейпов')
    toastError(toast, 'Не удалось загрузить статус скрейпов', error, 'Не удалось загрузить статус скрейпов')
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
    toastSuccess(toast, 'Scrape поставлен в очередь', shop.name)
    await loadDashboard()
  } catch (error) {
    errorMessage.value = messageFromError(error, 'Не удалось перезапустить scrape')
    toastError(toast, 'Не удалось перезапустить scrape', error, 'Не удалось перезапустить scrape')
  } finally {
    retryingShopId.value = null
  }
}

watch([selectedSource, selectedStatus], () => {
  void loadDashboard()
})

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  void loadDashboard()
})

onBeforeUnmount(() => {
  dashboardRequest?.abort()
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 2xl:flex-row 2xl:items-end 2xl:justify-between">
      <div>
        <p class="inline-flex items-center gap-2 text-sm font-medium text-admin-link">
          <Icon :icon="icons.activity" class="size-4" aria-hidden="true" />
          Статус скрейпов
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-admin-text">Здоровье источников</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-admin-text-muted">
          Смотрим последние запуски, упавшие магазины, устаревшие источники и расписание следующих запусков.
        </p>
      </div>

      <button
        type="button"
        class="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-md border border-admin-border-strong bg-admin-surface-muted px-3 text-sm font-medium text-admin-text-muted transition hover:border-admin-primary hover:bg-admin-surface-hover hover:text-admin-text"
        @click="openRecentRunsModal"
      >
        <Icon :icon="icons.timeline" class="size-4" aria-hidden="true" />
        Последние скрейпы
      </button>
    </div>

    <div class="grid gap-4 md:grid-cols-4">
      <div class="rounded-lg border border-admin-border bg-admin-surface p-5">
        <p class="inline-flex items-center gap-2 text-sm text-admin-text-faint">
          <Icon :icon="icons.buildingStore" class="size-4" aria-hidden="true" />
          Магазины
        </p>
        <p class="mt-3 text-3xl font-semibold text-admin-text">{{ shops.length }}</p>
      </div>
      <div class="rounded-lg border border-admin-border bg-admin-surface p-5">
        <p class="inline-flex items-center gap-2 text-sm text-admin-text-faint">
          <Icon :icon="icons.alertTriangle" class="size-4" aria-hidden="true" />
          Failed / partial
        </p>
        <p class="mt-3 text-3xl font-semibold" :class="failedOrPartialRuns > 0 ? 'text-admin-danger' : 'text-admin-text'">
          {{ failedOrPartialRuns }}
        </p>
      </div>
      <div class="rounded-lg border border-admin-border bg-admin-surface p-5">
        <p class="inline-flex items-center gap-2 text-sm text-admin-text-faint">
          <Icon :icon="icons.calendarDue" class="size-4" aria-hidden="true" />
          Due now
        </p>
        <p class="mt-3 text-3xl font-semibold" :class="dueShops > 0 ? 'text-admin-link' : 'text-admin-text'">
          {{ dueShops }}
        </p>
      </div>
      <div class="rounded-lg border border-admin-border bg-admin-surface p-5">
        <p class="inline-flex items-center gap-2 text-sm text-admin-text-faint">
          <Icon :icon="icons.clock" class="size-4" aria-hidden="true" />
          Последний запуск
        </p>
        <p class="mt-3 text-lg font-semibold text-admin-text">
          {{ mostRecentRun ? formatDateTime(mostRecentRun.started_at) : '-' }}
        </p>
      </div>
    </div>

    <div class="space-y-3">
      <div class="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div class="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-admin-text-faint">
          <Icon :icon="icons.buildingStore" class="size-4" aria-hidden="true" />
          Магазины
        </div>

        <div
          class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-end"
          data-testid="scrape-dashboard-filters"
        >
          <select
            v-model="selectedSource"
            aria-label="Фильтр скрейпов по источнику"
            class="h-10 min-w-56 rounded-md border border-admin-border bg-admin-surface-muted px-3 text-sm text-admin-text outline-none transition focus:border-admin-focus"
          >
            <option value="">Все источники</option>
            <option v-for="source in sourceOptions" :key="source" :value="source">
              {{ source }}
            </option>
          </select>
          <select
            v-model="selectedStatus"
            aria-label="Фильтр скрейпов по статусу"
            class="h-10 min-w-56 rounded-md border border-admin-border bg-admin-surface-muted px-3 text-sm text-admin-text outline-none transition focus:border-admin-focus"
          >
            <option value="">Все статусы</option>
            <option v-for="status in statusOptions" :key="status" :value="status">
              {{ statusLabel(status) }}
            </option>
          </select>
        </div>
      </div>

      <div class="overflow-x-auto rounded-lg border border-admin-border bg-admin-surface">
        <div
          class="grid min-w-[1020px] grid-cols-[minmax(220px,1.5fr)_110px_130px_170px_170px_minmax(150px,1fr)_150px] border-b border-admin-border px-4 py-3 text-xs font-semibold uppercase tracking-wide text-admin-text-faint"
        >
          <span>Магазин</span>
          <span>Источник</span>
          <span>Статус</span>
          <span>Последний scrape</span>
          <span>Следующий scrape</span>
          <span>Адрес</span>
          <span>Действие</span>
        </div>

        <div v-if="isLoading" class="min-w-[1020px] px-4 py-14 text-center text-sm text-admin-text-faint">
          <Icon :icon="icons.activity" class="mx-auto mb-3 size-6 text-admin-text-faint" aria-hidden="true" />
          Загружаем магазины...
        </div>

        <div
          v-else-if="shops.length === 0"
          class="min-w-[1020px] px-4 py-14 text-center text-sm text-admin-text-faint"
        >
          <Icon :icon="icons.search" class="mx-auto mb-3 size-6 text-admin-text-faint" aria-hidden="true" />
          По этим фильтрам магазинов не найдено.
        </div>

        <div v-else class="min-w-[1020px] divide-y divide-admin-border">
          <div
            v-for="shop in shops"
            :key="shop.id"
            class="grid grid-cols-[minmax(220px,1.5fr)_110px_130px_170px_170px_minmax(150px,1fr)_150px] px-4 py-4 text-sm"
            data-testid="scrape-shop-row"
          >
            <div class="min-w-0 pr-5">
              <p class="truncate font-medium text-admin-text" :title="shop.name">{{ shop.name }}</p>
              <p class="mt-1 truncate text-xs text-admin-text-faint" :title="shop.source_id">{{ shop.source_id }}</p>
            </div>
            <div class="text-admin-text-muted">{{ shop.source }}</div>
            <div>
              <span class="rounded-full border px-2 py-1 text-xs" :class="statusClass(shop.scrape_status)">
                {{ statusLabel(shop.scrape_status) }}
              </span>
              <p
                v-if="shop.enqueue_failed"
                class="mt-2 truncate text-xs text-admin-danger"
                :title="enqueueFailureTitle(shop)"
              >
                enqueue: {{ shop.enqueue_failed.reason }}
              </p>
            </div>
            <div class="text-admin-text-muted">{{ formatDateTime(shop.last_scraped_at) }}</div>
            <div class="text-admin-text-muted">{{ formatDateTime(shop.next_scrape_at) }}</div>
            <div class="min-w-0 pr-5 text-admin-text-faint">
              <p class="truncate" :title="shop.address || '-'">{{ shop.address || '-' }}</p>
            </div>
            <div>
              <button
                v-if="canRetryShop(shop)"
                type="button"
                class="inline-flex h-8 items-center justify-center gap-2 rounded-md border border-admin-border-strong bg-admin-surface-muted px-3 text-xs font-medium text-admin-link transition hover:border-admin-primary hover:bg-admin-surface-hover hover:text-admin-link-hover disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="retryingShopId === shop.id"
                @click="retryScrape(shop)"
              >
                <Icon :icon="icons.refresh" class="size-3.5" aria-hidden="true" />
                {{ retryingShopId === shop.id ? 'Ставим...' : 'Перезапуск' }}
              </button>
              <span v-else class="text-xs text-admin-text-faint">-</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <Teleport to="body">
      <div
        v-if="isRecentRunsModalOpen"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        @click.self="closeRecentRunsModal"
      >
        <section
          role="dialog"
          aria-modal="true"
          aria-labelledby="recent-runs-title"
          class="flex max-h-[calc(100vh-2rem)] w-full max-w-4xl flex-col overflow-hidden rounded-lg border border-admin-border bg-admin-surface shadow-xl"
        >
          <header class="flex items-start justify-between gap-4 border-b border-admin-border px-5 py-4">
            <div>
              <p id="recent-runs-title" class="text-base font-semibold text-admin-text">Последние скрейпы</p>
              <p class="mt-1 text-sm text-admin-text-faint">
                Последние {{ recentRuns.length }} запусков по выбранным фильтрам
              </p>
            </div>
            <button
              type="button"
              aria-label="Закрыть"
              class="inline-flex size-9 shrink-0 items-center justify-center rounded-md border border-admin-border bg-admin-surface-muted text-admin-text-muted transition hover:border-admin-primary hover:bg-admin-surface-hover hover:text-admin-text"
              @click="closeRecentRunsModal"
            >
              <Icon :icon="icons.x" class="size-4" aria-hidden="true" />
            </button>
          </header>

          <div class="overflow-y-auto">
            <div v-if="isLoading" class="px-5 py-14 text-center text-sm text-admin-text-faint">
              <Icon :icon="icons.timeline" class="mx-auto mb-3 size-6 text-admin-text-faint" aria-hidden="true" />
              Загружаем запуски...
            </div>

            <div v-else-if="recentRuns.length === 0" class="px-5 py-14 text-center text-sm text-admin-text-faint">
              <Icon :icon="icons.search" class="mx-auto mb-3 size-6 text-admin-text-faint" aria-hidden="true" />
              Запусков по этим фильтрам нет.
            </div>

            <div v-else class="divide-y divide-admin-border">
              <div
                v-for="run in recentRuns"
                :key="run.id"
                class="p-5 text-sm"
                data-testid="scrape-run-row"
              >
                <div class="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p class="font-medium text-admin-text">#{{ run.id }} · {{ run.source }}</p>
                    <p class="mt-1 text-xs text-admin-text-faint">
                      shop {{ run.shop_id || '-' }} · {{ formatDuration(run) }}
                    </p>
                  </div>
                  <span class="rounded-full border px-2 py-1 text-xs" :class="statusClass(run.status)">
                    {{ statusLabel(run.status) }}
                  </span>
                </div>
                <div class="mt-3 grid gap-2 text-xs text-admin-text-faint sm:grid-cols-2">
                  <p>started: {{ formatDateTime(run.started_at) }}</p>
                  <p>finished: {{ formatDateTime(run.finished_at) }}</p>
                  <p>seen: {{ run.items_seen }}</p>
                  <p>saved: {{ run.items_saved }}</p>
                </div>
                <p v-if="run.error" class="mt-3 rounded-md bg-admin-danger-soft px-3 py-2 text-xs text-admin-danger">
                  {{ run.error }}
                </p>
              </div>
            </div>
          </div>
        </section>
      </div>
    </Teleport>
  </section>
</template>
