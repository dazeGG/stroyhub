<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import {
  approveShopSourceCandidate,
  fetchShopSourceCandidates,
  refreshShopSourceCandidates,
  runShopScrape,
  type ShopSourceCandidate,
  type ShopSourceCandidateRefreshResponse,
  type ShopSourceCandidateStatus,
} from '../lib/api'
import { icons } from '../lib/icons'

const candidates = ref<ShopSourceCandidate[]>([])
const selectedStatus = ref<ShopSourceCandidateStatus | ''>('')
const isLoading = ref(false)
const isRefreshing = ref(false)
const approvingCandidateId = ref<number | null>(null)
const scrapingShopId = ref<number | null>(null)
const errorMessage = ref('')
const saveMessage = ref('')
const lastRefresh = ref<ShopSourceCandidateRefreshResponse | null>(null)
const approvedSource = ref<{ id: number, name: string } | null>(null)

let candidateRequest: AbortController | null = null

const pendingCount = computed(() => {
  return candidates.value.filter((candidate) => candidate.status === 'pending').length
})

const staleCount = computed(() => {
  return candidates.value.filter((candidate) => candidate.status === 'stale').length
})

const pricedCount = computed(() => {
  return candidates.value.filter((candidate) => candidate.has_prices).length
})

const websiteCount = computed(() => {
  return candidates.value.filter((candidate) => candidate.has_website).length
})

function statusLabel(status: ShopSourceCandidateStatus): string {
  const labels: Record<ShopSourceCandidateStatus, string> = {
    pending: 'Ожидает решения',
    stale: 'Не найден в последнем обновлении',
    hidden: 'Скрыт',
    archived: 'В архиве',
    approved: 'Утвержден',
  }

  return labels[status]
}

function statusClass(status: ShopSourceCandidateStatus): string {
  if (status === 'pending') {
    return 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'
  }
  if (status === 'stale') {
    return 'border-amber-400/30 bg-amber-400/10 text-amber-200'
  }
  if (status === 'approved') {
    return 'border-sky-400/30 bg-sky-400/10 text-sky-200'
  }

  return 'border-neutral-700 bg-neutral-900 text-neutral-400'
}

function canApprove(candidate: ShopSourceCandidate): boolean {
  return candidate.status === 'pending' || candidate.status === 'stale'
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return 'Нет данных'
  }

  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

async function loadCandidates(): Promise<void> {
  candidateRequest?.abort()
  const request = new AbortController()
  candidateRequest = request
  isLoading.value = true
  errorMessage.value = ''

  try {
    const response = await fetchShopSourceCandidates(
      {
        status: selectedStatus.value,
      },
      request.signal,
    )
    candidates.value = response.items
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }
    errorMessage.value = error instanceof Error ? error.message : 'Не удалось загрузить кандидатов'
    candidates.value = []
  } finally {
    if (candidateRequest === request) {
      isLoading.value = false
    }
  }
}

async function refreshCandidates(): Promise<void> {
  isRefreshing.value = true
  errorMessage.value = ''
  saveMessage.value = ''
  approvedSource.value = null

  try {
    const response = await refreshShopSourceCandidates()
    lastRefresh.value = response
    if (selectedStatus.value) {
      await loadCandidates()
    } else {
      candidates.value = response.items
    }
    saveMessage.value = `Обновлено из 2GIS: проверено ${response.checked}, новых ${response.created}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Не удалось обновить кандидатов'
  } finally {
    isRefreshing.value = false
  }
}

async function approveCandidate(
  candidate: ShopSourceCandidate,
  shopIdentityId?: number,
): Promise<void> {
  approvingCandidateId.value = candidate.id
  errorMessage.value = ''
  saveMessage.value = ''
  approvedSource.value = null

  try {
    const approvedCandidate = await approveShopSourceCandidate(candidate.id, shopIdentityId)
    approvedSource.value = approvedCandidate.approved_shop_id
      ? { id: approvedCandidate.approved_shop_id, name: candidate.display_name }
      : null
    const approvalTarget = shopIdentityId && candidate.suggested_identity
      ? `как филиал ${candidate.suggested_identity.display_name}`
      : 'в магазины'
    saveMessage.value = `${candidate.display_name} добавлен ${approvalTarget}. Товары ещё не загружены.`
    await loadCandidates()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Не удалось утвердить кандидата'
  } finally {
    approvingCandidateId.value = null
  }
}

async function scrapeApprovedSource(): Promise<void> {
  if (!approvedSource.value) {
    return
  }

  scrapingShopId.value = approvedSource.value.id
  errorMessage.value = ''

  try {
    const result = await runShopScrape(approvedSource.value.id)
    saveMessage.value = result.status === 'success'
      ? `${approvedSource.value.name}: товары загружены, сохранено ${result.products_saved ?? 0}`
      : `${approvedSource.value.name}: загрузка завершилась со статусом ${result.status}`
    approvedSource.value = null
    await loadCandidates()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Не удалось загрузить товары'
  } finally {
    scrapingShopId.value = null
  }
}

onMounted(() => {
  void loadCandidates()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
      <div>
        <RouterLink
          to="/shops"
          class="mb-5 mr-3 inline-flex h-9 items-center gap-2 rounded-md border border-neutral-800 bg-neutral-900/40 px-3 text-sm font-medium text-neutral-300 transition hover:border-amber-300/50 hover:text-white"
        >
          <Icon :icon="icons.arrowLeft" class="size-4" aria-hidden="true" />
          Магазины
        </RouterLink>
        <p class="inline-flex items-center gap-2 text-sm font-medium text-amber-300">
          <Icon :icon="icons.databaseImport" class="size-4" aria-hidden="true" />
          Кандидаты источников
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-white">Подтверждение магазинов из 2GIS</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
          Новые магазины попадают сюда перед тем, как стать отслеживаемыми источниками. Приоритет выше у кандидатов с ценами и сайтом.
        </p>
      </div>
    </div>

    <div v-if="errorMessage" class="rounded-lg border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-100">
      {{ errorMessage }}
    </div>
    <div
      v-if="saveMessage"
      class="flex flex-col gap-3 rounded-lg border border-emerald-400/30 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100 sm:flex-row sm:items-center sm:justify-between"
    >
      <span>{{ saveMessage }}</span>
      <button
        v-if="approvedSource"
        type="button"
        class="inline-flex h-9 w-fit items-center justify-center gap-2 rounded-md bg-emerald-300 px-3 text-xs font-semibold text-neutral-950 transition hover:bg-emerald-200 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="scrapingShopId === approvedSource.id"
        @click="scrapeApprovedSource"
      >
        <Icon :icon="icons.refresh" class="size-3.5" aria-hidden="true" />
        {{ scrapingShopId === approvedSource.id ? 'Загружаем...' : 'Загрузить товары' }}
      </button>
    </div>

    <div class="grid gap-4 md:grid-cols-4">
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="inline-flex items-center gap-2 text-sm text-neutral-500">
          <Icon :icon="icons.listCheck" class="size-4" aria-hidden="true" />
          Ожидают
        </p>
        <p class="mt-3 text-3xl font-semibold text-white">{{ pendingCount }}</p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="inline-flex items-center gap-2 text-sm text-neutral-500">
          <Icon :icon="icons.currencyRubel" class="size-4" aria-hidden="true" />
          С ценами
        </p>
        <p class="mt-3 text-3xl font-semibold text-white">{{ pricedCount }}</p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="inline-flex items-center gap-2 text-sm text-neutral-500">
          <Icon :icon="icons.externalLink" class="size-4" aria-hidden="true" />
          С сайтом
        </p>
        <p class="mt-3 text-3xl font-semibold text-white">{{ websiteCount }}</p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="inline-flex items-center gap-2 text-sm text-neutral-500">
          <Icon :icon="icons.alertTriangle" class="size-4" aria-hidden="true" />
          Пропали
        </p>
        <p class="mt-3 text-3xl font-semibold" :class="staleCount > 0 ? 'text-amber-200' : 'text-white'">
          {{ staleCount }}
        </p>
      </div>
    </div>

    <div
      v-if="lastRefresh"
      class="grid gap-3 rounded-lg border border-neutral-800 bg-neutral-900/40 p-4 text-sm text-neutral-400 md:grid-cols-5"
    >
      <p>Проверено: <span class="text-neutral-100">{{ lastRefresh.checked }}</span></p>
      <p>Новых: <span class="text-neutral-100">{{ lastRefresh.created }}</span></p>
      <p>Обновлено: <span class="text-neutral-100">{{ lastRefresh.updated }}</span></p>
      <p>Пропали: <span class="text-neutral-100">{{ lastRefresh.stale }}</span></p>
      <p>Уже утверждены: <span class="text-neutral-100">{{ lastRefresh.skipped_approved }}</span></p>
    </div>

    <div class="flex flex-col gap-3 border-t border-neutral-800 pt-5 lg:flex-row lg:items-center lg:justify-between">
      <div>
        <h3 class="text-base font-semibold text-white">Магазины 2GIS</h3>
        <p class="mt-1 text-sm text-neutral-500">Кандидаты из поиска 2GIS с полезными сигналами для добавления источников.</p>
      </div>
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
        <select
          v-model="selectedStatus"
          aria-label="Фильтр кандидатов по статусу"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
          @change="loadCandidates"
        >
          <option value="">Все кандидаты</option>
          <option value="pending">Ожидают решения</option>
          <option value="stale">Не найдены в последнем обновлении</option>
          <option value="hidden">Скрытые</option>
          <option value="archived">Архив</option>
        </select>
        <button
          type="button"
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-amber-300 px-4 text-sm font-semibold text-neutral-950 transition hover:bg-amber-200 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="isRefreshing"
          @click="refreshCandidates"
        >
          <Icon :icon="icons.refresh" class="size-4" aria-hidden="true" />
          {{ isRefreshing ? 'Обновляем...' : 'Обновить из 2GIS' }}
        </button>
      </div>
    </div>

    <div v-if="isLoading" class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-8 text-center text-sm text-neutral-500">
      Загружаем кандидатов...
    </div>

    <div v-else-if="candidates.length === 0" class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-8 text-center">
      <Icon :icon="icons.databaseImport" class="mx-auto mb-3 size-7 text-neutral-600" aria-hidden="true" />
      <p class="text-sm font-medium text-neutral-200">Кандидатов пока нет</p>
      <p class="mt-2 text-sm text-neutral-500">Обновите список из 2GIS, чтобы загрузить магазины на подтверждение.</p>
    </div>

    <div v-else class="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
      <article
        v-for="candidate in candidates"
        :key="candidate.id"
        class="flex min-h-[260px] flex-col rounded-lg border border-neutral-800 bg-neutral-900/40 p-4"
      >
        <div class="min-h-[92px]">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="text-base font-semibold text-white">{{ candidate.display_name }}</h3>
              <span class="rounded-full border px-2 py-0.5 text-xs font-medium" :class="statusClass(candidate.status)">
                {{ statusLabel(candidate.status) }}
              </span>
              <span
                v-if="candidate.official_strategy"
                class="inline-flex items-center gap-1 rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 text-xs font-medium text-amber-100"
              >
                <Icon :icon="icons.shieldLock" class="size-3.5" aria-hidden="true" />
                {{ candidate.official_strategy.label }}
              </span>
            </div>
            <p class="mt-2 text-sm text-neutral-500">{{ candidate.address || 'Адрес не указан' }}</p>
            <p class="mt-1 font-mono text-xs text-neutral-600">2GIS · {{ candidate.source_id }}</p>
          </div>
        </div>

        <div class="mt-4 grid flex-1 gap-4 border-t border-neutral-800 pt-4 text-sm text-neutral-400">
          <div>
            <p class="text-xs uppercase tracking-wide text-neutral-600">Сигналы 2GIS</p>
            <div class="mt-2 flex flex-wrap gap-2">
              <span
                v-if="candidate.has_prices"
                class="inline-flex items-center gap-1 rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2.5 py-1 text-xs font-medium text-emerald-200"
              >
                <Icon :icon="icons.currencyRubel" class="size-3.5" aria-hidden="true" />
                Есть товары и цены
              </span>
              <span
                v-if="candidate.has_website"
                class="inline-flex items-center gap-1 rounded-full border border-sky-400/30 bg-sky-400/10 px-2.5 py-1 text-xs font-medium text-sky-200"
              >
                <Icon :icon="icons.externalLink" class="size-3.5" aria-hidden="true" />
                Есть сайт
              </span>
            </div>
            <p class="mt-2 text-xs text-neutral-500">
              Ссылка на сайт и товары подтягиваются после утверждения источника.
            </p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-neutral-600">Последняя проверка</p>
            <p class="mt-2 text-neutral-200">{{ formatDateTime(candidate.last_checked_at) }}</p>
            <p v-if="candidate.missing_since" class="mt-1 text-xs text-amber-200">
              Не найден с {{ formatDateTime(candidate.missing_since) }}
            </p>
          </div>
          <div
            v-if="candidate.suggested_identity"
            class="rounded-md border border-amber-400/20 bg-amber-400/5 p-3"
          >
            <p class="text-xs uppercase tracking-wide text-amber-200/70">Похожий магазин</p>
            <div class="mt-2 flex flex-wrap items-center gap-2">
              <p class="font-medium text-amber-50">{{ candidate.suggested_identity.display_name }}</p>
              <span class="rounded-full border border-amber-300/30 px-2 py-0.5 text-xs text-amber-100">
                источников: {{ candidate.suggested_identity.source_count }}
              </span>
            </div>
            <p class="mt-2 text-xs text-neutral-500">
              Можно добавить этот 2GIS-адрес как филиал существующего магазина.
            </p>
          </div>
        </div>

        <div class="mt-4 flex flex-wrap justify-end gap-2">
          <button
            v-if="candidate.suggested_identity"
            type="button"
            class="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-neutral-700 px-3 text-xs font-semibold text-neutral-300 transition hover:border-amber-300 hover:text-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="!canApprove(candidate) || approvingCandidateId === candidate.id"
            @click="approveCandidate(candidate)"
          >
            Создать отдельно
          </button>
          <button
            type="button"
            class="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-emerald-300 px-3 text-xs font-semibold text-neutral-950 transition hover:bg-emerald-200 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="!canApprove(candidate) || approvingCandidateId === candidate.id"
            @click="approveCandidate(candidate, candidate.suggested_identity?.id)"
          >
            <Icon :icon="icons.check" class="size-3.5" aria-hidden="true" />
            {{
              approvingCandidateId === candidate.id
                ? 'Добавляем...'
                : candidate.suggested_identity
                  ? 'Добавить филиалом'
                  : 'Утвердить'
            }}
          </button>
        </div>
      </article>
    </div>
  </section>
</template>
