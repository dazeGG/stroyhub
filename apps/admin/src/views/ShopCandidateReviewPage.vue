<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { useToast } from '@nuxt/ui/composables'
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import {
  approveShopSourceCandidate,
  fetchOperationStatus,
  fetchShopSourceCandidates,
  materializeOfficialStrategy,
  refreshShopSourceCandidates,
  verifyShopSourceCandidateTwogisData,
  type ShopSourceCandidate,
  type ShopSourceCandidateGroup,
  type ShopSourceCandidateRefreshResult,
  type ShopSourceCandidateVerificationResult,
  type ShopSourceCandidateStatus,
} from '../lib/api'
import { icons } from '../lib/icons'
import { messageFromError, toastError, toastSuccess } from '../lib/notifications'

const candidates = ref<ShopSourceCandidate[]>([])
const candidateGroups = ref<ShopSourceCandidateGroup[]>([])
const selectedStatus = ref<ShopSourceCandidateStatus | ''>('')
const isLoading = ref(false)
const isRefreshing = ref(false)
const approvingCandidateId = ref<number | null>(null)
const verifyingCandidateId = ref<number | null>(null)
const materializingOfficialSource = ref<string | null>(null)
const errorMessage = ref('')
const saveMessage = ref('')
const toast = useToast()
const lastRefresh = ref<ShopSourceCandidateRefreshResult | null>(null)

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

const groupedCandidateIds = computed(() => {
  return new Set(candidateGroups.value.flatMap((group) => group.candidate_ids))
})

const ungroupedCandidates = computed(() => {
  return candidates.value.filter((candidate) => !groupedCandidateIds.value.has(candidate.id))
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
    return 'border-admin-success-border bg-admin-success-soft text-admin-success'
  }
  if (status === 'stale') {
    return 'border-admin-border-strong bg-admin-surface-muted text-admin-link'
  }
  if (status === 'approved') {
    return 'border-admin-border-strong bg-admin-surface-muted text-admin-text'
  }

  return 'border-admin-border-strong bg-admin-surface-muted text-admin-text-muted'
}

function canApprove(candidate: ShopSourceCandidate): boolean {
  return candidate.status === 'pending' || candidate.status === 'stale'
}

function canVerify(candidate: ShopSourceCandidate): boolean {
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
    candidateGroups.value = response.groups
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }
    errorMessage.value = messageFromError(error, 'Не удалось загрузить кандидатов')
    toastError(toast, 'Не удалось загрузить кандидатов', error, 'Не удалось загрузить кандидатов')
    candidates.value = []
    candidateGroups.value = []
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

  try {
    const operation = await refreshShopSourceCandidates()
    saveMessage.value = `Обновление из 2GIS поставлено в очередь: ${operation.task_id}`
    const result = await waitForOperation<ShopSourceCandidateRefreshResult>(operation.task_id)
    lastRefresh.value = result
    await loadCandidates()
    saveMessage.value = `Обновлено из 2GIS: проверено ${result.checked}, новых ${result.created}`
    toastSuccess(toast, 'Кандидаты обновлены', saveMessage.value)
  } catch (error) {
    errorMessage.value = messageFromError(error, 'Не удалось обновить кандидатов')
    toastError(toast, 'Не удалось обновить кандидатов', error, 'Не удалось обновить кандидатов')
  } finally {
    isRefreshing.value = false
  }
}

async function materializeOfficialGroup(group: ShopSourceCandidateGroup): Promise<void> {
  const source = group.official_strategy?.source
  if (!source) {
    return
  }
  materializingOfficialSource.value = source
  errorMessage.value = ''
  saveMessage.value = ''

  try {
    const response = await materializeOfficialStrategy(source, true)
    const scrapeResult = response.scrape_result
    const scrapeMessage = formatScrapeMessage(scrapeResult)
    saveMessage.value = `${response.shop.name}: официальный источник ${response.shop.source} создан/обновлен. ${scrapeMessage}`
    toastSuccess(toast, 'Официальный источник готов', saveMessage.value)
    await loadCandidates()
  } catch (error) {
    errorMessage.value = messageFromError(error, 'Не удалось создать официальный источник')
    toastError(
      toast,
      'Не удалось создать официальный источник',
      error,
      'Не удалось создать официальный источник',
    )
  } finally {
    materializingOfficialSource.value = null
  }
}

async function approveCandidate(
  candidate: ShopSourceCandidate,
  shopIdentityId?: number,
): Promise<void> {
  approvingCandidateId.value = candidate.id
  errorMessage.value = ''
  saveMessage.value = ''

  try {
    const approvedCandidate = await approveShopSourceCandidate(candidate.id, shopIdentityId)
    const approvalTarget = shopIdentityId && candidate.suggested_identity
      ? `как филиал ${candidate.suggested_identity.display_name}`
      : 'в магазины'
    const scrapeResult = approvedCandidate.scrape_result
    const scrapeMessage = formatScrapeMessage(scrapeResult)
    saveMessage.value = `${candidate.display_name} добавлен ${approvalTarget}. ${scrapeMessage}`
    toastSuccess(toast, 'Кандидат утвержден', saveMessage.value)
    await loadCandidates()
  } catch (error) {
    errorMessage.value = messageFromError(error, 'Не удалось утвердить кандидата')
    toastError(toast, 'Не удалось утвердить кандидата', error, 'Не удалось утвердить кандидата')
  } finally {
    approvingCandidateId.value = null
  }
}

async function verifyCandidate(candidate: ShopSourceCandidate): Promise<void> {
  verifyingCandidateId.value = candidate.id
  errorMessage.value = ''
  saveMessage.value = ''

  try {
    const operation = await verifyShopSourceCandidateTwogisData(candidate.id)
    saveMessage.value = `${candidate.display_name}: проверка 2GIS поставлена в очередь`
    const result = await waitForOperation<ShopSourceCandidateVerificationResult>(operation.task_id)
    await loadCandidates()
    const message = formatVerificationMessage(result)
    saveMessage.value = `${candidate.display_name}: ${message}`
    toastSuccess(toast, 'Данные 2GIS проверены', saveMessage.value)
  } catch (error) {
    errorMessage.value = messageFromError(error, 'Не удалось проверить данные 2GIS')
    toastError(toast, 'Не удалось проверить данные 2GIS', error, 'Не удалось проверить данные 2GIS')
  } finally {
    verifyingCandidateId.value = null
  }
}

function formatVerificationMessage(
  response: ShopSourceCandidateVerificationResult,
): string {
  const website = response.website_found
    ? `сайт подтвержден${response.website_url ? `: ${response.website_url}` : ''}`
    : 'сайт не найден'
  const products = response.products_found
    ? `товары подтверждены: ${response.product_count}`
    : 'товары не найдены'
  return `${website}; ${products}`
}

function formatScrapeMessage(scrapeResult: ShopSourceCandidate['scrape_result']): string {
  if (scrapeResult?.status === 'queued') {
    return 'Загрузка поставлена в очередь.'
  }
  if (scrapeResult?.status === 'success') {
    return `Товары загружены, сохранено ${scrapeResult.products_saved ?? 0}.`
  }
  return `Загрузка завершилась со статусом ${scrapeResult?.status || 'unknown'}.`
}

async function waitForOperation<T>(taskId: string): Promise<T> {
  for (let attempt = 0; attempt < 90; attempt += 1) {
    const operation = await fetchOperationStatus<T>(taskId)
    if (operation.status === 'success' && operation.result !== undefined) {
      return operation.result
    }
    if (operation.status === 'failed') {
      throw new Error(operation.error || 'Операция завершилась с ошибкой')
    }

    await delay(attempt < 5 ? 1000 : 2000)
  }

  throw new Error('Операция не завершилась за отведенное время')
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
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
          class="mb-5 mr-3 inline-flex h-9 items-center gap-2 rounded-md border border-admin-border bg-admin-surface px-3 text-sm font-medium text-admin-text-muted transition hover:border-admin-border-strong hover:text-admin-text"
        >
          <Icon :icon="icons.arrowLeft" class="size-4" aria-hidden="true" />
          Магазины
        </RouterLink>
        <p class="inline-flex items-center gap-2 text-sm font-medium text-admin-link">
          <Icon :icon="icons.databaseImport" class="size-4" aria-hidden="true" />
          Кандидаты источников
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-admin-text">Подтверждение магазинов из 2GIS</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-admin-text-muted">
          Новые магазины попадают сюда перед тем, как стать отслеживаемыми источниками. Приоритет выше у кандидатов с ценами и сайтом.
        </p>
      </div>
    </div>

    <div class="grid gap-4 md:grid-cols-4">
      <div class="rounded-lg border border-admin-border bg-admin-surface p-5">
        <p class="inline-flex items-center gap-2 text-sm text-admin-text-faint">
          <Icon :icon="icons.listCheck" class="size-4" aria-hidden="true" />
          Ожидают
        </p>
        <p class="mt-3 text-3xl font-semibold text-admin-text">{{ pendingCount }}</p>
      </div>
      <div class="rounded-lg border border-admin-border bg-admin-surface p-5">
        <p class="inline-flex items-center gap-2 text-sm text-admin-text-faint">
          <Icon :icon="icons.currencyRubel" class="size-4" aria-hidden="true" />
          С ценами
        </p>
        <p class="mt-3 text-3xl font-semibold text-admin-text">{{ pricedCount }}</p>
      </div>
      <div class="rounded-lg border border-admin-border bg-admin-surface p-5">
        <p class="inline-flex items-center gap-2 text-sm text-admin-text-faint">
          <Icon :icon="icons.externalLink" class="size-4" aria-hidden="true" />
          С сайтом
        </p>
        <p class="mt-3 text-3xl font-semibold text-admin-text">{{ websiteCount }}</p>
      </div>
      <div class="rounded-lg border border-admin-border bg-admin-surface p-5">
        <p class="inline-flex items-center gap-2 text-sm text-admin-text-faint">
          <Icon :icon="icons.alertTriangle" class="size-4" aria-hidden="true" />
          Пропали
        </p>
        <p class="mt-3 text-3xl font-semibold" :class="staleCount > 0 ? 'text-admin-link' : 'text-admin-text'">
          {{ staleCount }}
        </p>
      </div>
    </div>

    <div
      v-if="lastRefresh"
      class="grid gap-3 rounded-lg border border-admin-border bg-admin-surface p-4 text-sm text-admin-text-muted md:grid-cols-5"
    >
      <p>Проверено: <span class="text-admin-text">{{ lastRefresh.checked }}</span></p>
      <p>Новых: <span class="text-admin-text">{{ lastRefresh.created }}</span></p>
      <p>Обновлено: <span class="text-admin-text">{{ lastRefresh.updated }}</span></p>
      <p>Пропали: <span class="text-admin-text">{{ lastRefresh.stale }}</span></p>
      <p>Уже утверждены: <span class="text-admin-text">{{ lastRefresh.skipped_approved }}</span></p>
    </div>

    <div class="flex flex-col gap-3 border-t border-admin-border pt-5 lg:flex-row lg:items-center lg:justify-between">
      <div>
        <h3 class="text-base font-semibold text-admin-text">Магазины 2GIS</h3>
        <p class="mt-1 text-sm text-admin-text-faint">Кандидаты из поиска 2GIS с полезными сигналами для добавления источников.</p>
      </div>
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
        <select
          v-model="selectedStatus"
          aria-label="Фильтр кандидатов по статусу"
          class="h-10 rounded-md border border-admin-border bg-admin-surface-muted px-3 text-sm text-admin-text outline-none transition focus:border-admin-focus"
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
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-admin-primary px-4 text-sm font-semibold text-admin-primary-text transition hover:bg-admin-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="isRefreshing"
          @click="refreshCandidates"
        >
          <Icon :icon="icons.refresh" class="size-4" aria-hidden="true" />
          {{ isRefreshing ? 'Обновляем...' : 'Обновить из 2GIS' }}
        </button>
      </div>
    </div>

    <div v-if="isLoading" class="rounded-lg border border-admin-border bg-admin-surface p-8 text-center text-sm text-admin-text-faint">
      Загружаем кандидатов...
    </div>

    <div v-else-if="candidates.length === 0" class="rounded-lg border border-admin-border bg-admin-surface p-8 text-center">
      <Icon :icon="icons.databaseImport" class="mx-auto mb-3 size-7 text-admin-text-faint" aria-hidden="true" />
      <p class="text-sm font-medium text-admin-text">Кандидатов пока нет</p>
      <p class="mt-2 text-sm text-admin-text-faint">Обновите список из 2GIS, чтобы загрузить магазины на подтверждение.</p>
    </div>

    <div v-else class="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
      <article
        v-for="group in candidateGroups"
        :key="group.key"
        class="flex min-h-[260px] flex-col rounded-lg border border-admin-border-strong bg-admin-surface p-4"
      >
        <div class="min-h-[92px]">
          <div class="flex flex-wrap items-center gap-2">
            <h3 class="text-base font-semibold text-admin-text">{{ group.label }}</h3>
            <span class="rounded-full border border-admin-border-strong bg-admin-surface-muted px-2 py-0.5 text-xs font-medium text-admin-text-muted">
              {{ group.size }} источника
            </span>
            <span
              v-if="group.official_strategy"
              class="inline-flex items-center gap-1 rounded-full border border-admin-border-strong bg-admin-surface-muted px-2 py-0.5 text-xs font-medium text-admin-link"
            >
              <Icon :icon="icons.shieldLock" class="size-3.5" aria-hidden="true" />
              {{ group.official_strategy.label }}
            </span>
          </div>
          <p class="mt-2 text-sm text-admin-text-faint">
            Группа похожих 2GIS-кандидатов. Source-записи остаются отдельными до решения оператора.
          </p>
        </div>

        <div class="mt-4 grid flex-1 gap-3 border-t border-admin-border pt-4">
          <div
            v-for="candidate in group.items"
            :key="candidate.id"
            class="rounded-md border border-admin-border bg-admin-surface-subtle p-3"
          >
            <div class="flex flex-wrap items-center gap-2">
              <p class="text-sm font-medium text-admin-text">{{ candidate.display_name }}</p>
              <span class="rounded-full border px-2 py-0.5 text-xs font-medium" :class="statusClass(candidate.status)">
                {{ statusLabel(candidate.status) }}
              </span>
            </div>
            <p class="mt-1 text-xs text-admin-text-faint">{{ candidate.address || 'Адрес не указан' }}</p>
            <p class="mt-1 font-mono text-xs text-admin-text-faint">2GIS · {{ candidate.source_id }}</p>
            <div class="mt-3 flex flex-wrap justify-end gap-2">
              <button
                type="button"
                class="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-admin-border-strong bg-admin-surface-muted px-2.5 text-xs font-semibold text-admin-text transition hover:border-admin-border-strong hover:bg-admin-surface-muted disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="!canVerify(candidate) || verifyingCandidateId === candidate.id"
                @click="verifyCandidate(candidate)"
              >
                <Icon :icon="icons.search" class="size-3.5" aria-hidden="true" />
                {{ verifyingCandidateId === candidate.id ? 'Проверяем...' : 'Проверить 2GIS' }}
              </button>
              <button
                v-if="candidate.suggested_identity"
                type="button"
                class="inline-flex h-8 items-center justify-center rounded-md border border-admin-border-strong px-2.5 text-xs font-semibold text-admin-text-muted transition hover:border-admin-primary hover:text-admin-link-hover disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="!canApprove(candidate) || approvingCandidateId === candidate.id"
                @click="approveCandidate(candidate)"
              >
                Создать отдельно
              </button>
              <button
                type="button"
                class="inline-flex h-8 items-center justify-center gap-1.5 rounded-md bg-admin-success px-2.5 text-xs font-semibold text-admin-primary-text transition hover:bg-admin-success disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="!canApprove(candidate) || approvingCandidateId === candidate.id"
                @click="approveCandidate(candidate, candidate.suggested_identity?.id)"
              >
                <Icon :icon="icons.check" class="size-3.5" aria-hidden="true" />
                {{
                  approvingCandidateId === candidate.id
                    ? 'Добавляем...'
                    : candidate.suggested_identity
                      ? 'Филиалом'
                      : 'Утвердить'
                }}
              </button>
            </div>
          </div>
        </div>

        <div class="mt-4 flex flex-wrap justify-end gap-2">
          <button
            v-if="group.official_strategy"
            type="button"
            class="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-admin-primary px-3 text-xs font-semibold text-admin-primary-text transition hover:bg-admin-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="materializingOfficialSource === group.official_strategy.source"
            @click="materializeOfficialGroup(group)"
          >
            <Icon :icon="icons.databaseImport" class="size-3.5" aria-hidden="true" />
            {{
              materializingOfficialSource === group.official_strategy.source
                ? 'Загружаем...'
                : group.items.some((item) => item.official_source_shop_id)
                  ? 'Загрузить official source'
                  : 'Создать official source'
            }}
          </button>
        </div>
      </article>
      <article
        v-for="candidate in ungroupedCandidates"
        :key="candidate.id"
        class="flex min-h-[260px] flex-col rounded-lg border border-admin-border bg-admin-surface p-4"
      >
        <div class="min-h-[92px]">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="text-base font-semibold text-admin-text">{{ candidate.display_name }}</h3>
              <span class="rounded-full border px-2 py-0.5 text-xs font-medium" :class="statusClass(candidate.status)">
                {{ statusLabel(candidate.status) }}
              </span>
              <span
                v-if="candidate.official_strategy"
                class="inline-flex items-center gap-1 rounded-full border border-admin-border-strong bg-admin-surface-muted px-2 py-0.5 text-xs font-medium text-admin-link"
              >
                <Icon :icon="icons.shieldLock" class="size-3.5" aria-hidden="true" />
                {{ candidate.official_strategy.label }}
              </span>
            </div>
            <p class="mt-2 text-sm text-admin-text-faint">{{ candidate.address || 'Адрес не указан' }}</p>
            <p class="mt-1 font-mono text-xs text-admin-text-faint">2GIS · {{ candidate.source_id }}</p>
          </div>
        </div>

        <div class="mt-4 grid flex-1 gap-4 border-t border-admin-border pt-4 text-sm text-admin-text-muted">
          <div>
            <p class="text-xs uppercase tracking-wide text-admin-text-faint">Сигналы 2GIS</p>
            <div class="mt-2 flex flex-wrap gap-2">
              <span
                v-if="candidate.has_prices"
                class="inline-flex items-center gap-1 rounded-full border border-admin-success-border bg-admin-success-soft px-2.5 py-1 text-xs font-medium text-admin-success"
              >
                <Icon :icon="icons.currencyRubel" class="size-3.5" aria-hidden="true" />
                Есть товары и цены
              </span>
              <span
                v-if="candidate.has_website"
                class="inline-flex items-center gap-1 rounded-full border border-admin-border-strong bg-admin-surface-muted px-2.5 py-1 text-xs font-medium text-admin-text"
              >
                <Icon :icon="icons.externalLink" class="size-3.5" aria-hidden="true" />
                Есть сайт
              </span>
            </div>
            <p class="mt-2 text-xs text-admin-text-faint">
              Ссылка на сайт и товары подтягиваются после утверждения источника.
            </p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-admin-text-faint">Последняя проверка</p>
            <p class="mt-2 text-admin-text">{{ formatDateTime(candidate.last_checked_at) }}</p>
            <p v-if="candidate.missing_since" class="mt-1 text-xs text-admin-link">
              Не найден с {{ formatDateTime(candidate.missing_since) }}
            </p>
          </div>
          <div
            v-if="candidate.suggested_identity"
            class="rounded-md border border-admin-border-strong bg-admin-surface-muted p-3"
          >
            <p class="text-xs uppercase tracking-wide text-admin-link">Похожий магазин</p>
            <div class="mt-2 flex flex-wrap items-center gap-2">
              <p class="font-medium text-admin-link">{{ candidate.suggested_identity.display_name }}</p>
              <span class="rounded-full border border-admin-border-strong px-2 py-0.5 text-xs text-admin-link">
                источников: {{ candidate.suggested_identity.source_count }}
              </span>
            </div>
            <p class="mt-2 text-xs text-admin-text-faint">
              Можно добавить этот 2GIS-адрес как филиал существующего магазина.
            </p>
          </div>
        </div>

        <div class="mt-4 flex flex-wrap justify-end gap-2">
          <button
            type="button"
            class="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-admin-border-strong bg-admin-surface-muted px-3 text-xs font-semibold text-admin-text transition hover:border-admin-border-strong hover:bg-admin-surface-muted disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="!canVerify(candidate) || verifyingCandidateId === candidate.id"
            @click="verifyCandidate(candidate)"
          >
            <Icon :icon="icons.search" class="size-3.5" aria-hidden="true" />
            {{ verifyingCandidateId === candidate.id ? 'Проверяем...' : 'Проверить 2GIS' }}
          </button>
          <button
            v-if="candidate.suggested_identity"
            type="button"
            class="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-admin-border-strong px-3 text-xs font-semibold text-admin-text-muted transition hover:border-admin-primary hover:text-admin-link-hover disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="!canApprove(candidate) || approvingCandidateId === candidate.id"
            @click="approveCandidate(candidate)"
          >
            Создать отдельно
          </button>
          <button
            type="button"
            class="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-admin-success px-3 text-xs font-semibold text-admin-primary-text transition hover:bg-admin-success disabled:cursor-not-allowed disabled:opacity-50"
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
