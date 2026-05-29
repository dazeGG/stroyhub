<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { useToast } from '@nuxt/ui/composables'
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import {
  decidePatronReviewItem,
  fetchPatronReviewItem,
  undoPatronReviewDecision,
  type PatronReviewAction,
  type PatronReviewItem,
  type PatronReviewMode,
  type PatronReviewParams,
  type PatronReviewStats,
} from '../lib/api'
import { icons } from '../lib/icons'
import { toastError, toastSuccess, toastWarning } from '../lib/notifications'

const emptyStats: PatronReviewStats = {
  total: 0,
  remaining: 0,
  reviewed: 0,
  skipped: 0,
}

const reviewModes: Array<{ value: PatronReviewMode; label: string; title: string; empty: string }> = [
  {
    value: 'needs_review',
    label: 'Текущий ревью',
    title: 'Проверка спорных карточек',
    empty: 'Все текущие Patron-карточки обработаны.',
  },
  {
    value: 'patron_rejected',
    label: 'Patron отклонил',
    title: 'Проверка отклоненных Patron карточек',
    empty: 'В выбранном пороге нет карточек, которые Patron отклонил.',
  },
]

const probabilityThresholds = [
  { value: 0.7, label: '70%+' },
  { value: 0.8, label: '80%+' },
  { value: 0.9, label: '90%+' },
  { value: 0.99, label: '99%+' },
]

const activeMode = ref<PatronReviewMode>('needs_review')
const minProbability = ref(0.7)
const item = ref<PatronReviewItem | null>(null)
const stats = ref<PatronReviewStats>(emptyStats)
const isLoading = ref(false)
const busyAction = ref('')
const reason = ref('')
const toast = useToast()
let loadRequestId = 0

const activeModeConfig = computed(() => {
  return reviewModes.find((mode) => mode.value === activeMode.value) ?? reviewModes[0]
})

const progressPercent = computed(() => {
  if (stats.value.total === 0) {
    return 100
  }
  return Math.round(((stats.value.reviewed + stats.value.skipped) / stats.value.total) * 100)
})

const reviewParams = computed<PatronReviewParams>(() => {
  if (activeMode.value === 'patron_rejected') {
    return {
      mode: activeMode.value,
      minProbability: minProbability.value,
    }
  }
  return { mode: activeMode.value }
})

const modelLabel = computed(() => {
  const eligibility = item.value?.catalog_eligibility
  const modelName = asString(eligibility?.model_name) ?? 'Patron'
  const modelVersion = asString(eligibility?.model_version)
  return modelVersion ? `${modelName} ${modelVersion}` : modelName
})

const probabilityLabel = computed(() => {
  const value = item.value?.catalog_eligibility?.not_product_probability
  return value === undefined || value === null ? '-' : confidencePercent(value)
})

const methodLabel = computed(() => {
  return asString(item.value?.catalog_eligibility?.method) ?? '-'
})

const reasonList = computed(() => {
  const reasons = item.value?.catalog_eligibility?.reasons
  return Array.isArray(reasons) ? reasons.map((value) => String(value)) : []
})

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

function confidencePercent(value: unknown): string {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? `${Math.round(numeric * 100)}%` : String(value)
}

function formatPrice(reviewItem: PatronReviewItem): string {
  if (!reviewItem.latest_price) {
    return 'Нет цены'
  }
  if (reviewItem.latest_price.price === null) {
    return reviewItem.latest_price.unit_raw
      ? `Цена не указана · ${reviewItem.latest_price.unit_raw}`
      : 'Цена не указана'
  }

  const value = new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: reviewItem.latest_price.currency,
    maximumFractionDigits: 2,
  }).format(Number(reviewItem.latest_price.price))
  const prefix = reviewItem.latest_price.price_kind === 'from' || reviewItem.latest_price.price_kind === 'range' ? 'от ' : ''
  return reviewItem.latest_price.unit_raw
    ? `${prefix}${value} · ${reviewItem.latest_price.unit_raw}`
    : `${prefix}${value}`
}

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

function rawJson(reviewItem: PatronReviewItem): string {
  return JSON.stringify(reviewItem.raw ?? {}, null, 2)
}

function actionKey(action: string): string {
  return item.value ? `${item.value.id}:${action}` : action
}

async function loadReviewItem(): Promise<void> {
  const requestId = ++loadRequestId
  isLoading.value = true
  try {
    const response = await fetchPatronReviewItem(reviewParams.value)
    if (requestId !== loadRequestId) {
      return
    }
    item.value = response.item
    stats.value = response.stats
  } catch (error) {
    if (requestId === loadRequestId) {
      toastError(toast, 'Не удалось загрузить Patron ревью', error, 'Не удалось загрузить Patron ревью')
    }
  } finally {
    if (requestId === loadRequestId) {
      isLoading.value = false
    }
  }
}

async function decide(action: PatronReviewAction): Promise<void> {
  if (!item.value) {
    return
  }

  busyAction.value = actionKey(action)
  try {
    const response = await decidePatronReviewItem(item.value.id, action, reason.value, reviewParams.value)
    stats.value = response.stats
    reason.value = ''
    toastSuccess(toast, 'Решение сохранено', actionLabel(action))
    await loadReviewItem()
  } catch (error) {
    toastError(toast, 'Не удалось сохранить решение', error, 'Не удалось сохранить решение')
  } finally {
    busyAction.value = ''
  }
}

async function undoPrevious(): Promise<void> {
  busyAction.value = 'undo'
  try {
    const response = await undoPatronReviewDecision(reason.value, reviewParams.value)
    stats.value = response.stats
    reason.value = ''
    toastSuccess(toast, 'Предыдущее решение отменено')
    await loadReviewItem()
  } catch (error) {
    toastWarning(toast, 'Нечего отменять', error instanceof Error ? error.message : 'История пуста.')
  } finally {
    busyAction.value = ''
  }
}

function actionLabel(action: PatronReviewAction): string {
  const labels: Record<PatronReviewAction, string> = {
    product: 'Товар',
    not_product: 'Не товар',
    skip: 'Скип',
  }
  return labels[action]
}

onMounted(() => {
  void loadReviewItem()
})

watch([activeMode, minProbability], () => {
  reason.value = ''
  void loadReviewItem()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
      <div>
        <p class="inline-flex items-center gap-2 text-sm font-medium text-admin-link">
          <Icon :icon="icons.shieldLock" class="size-4" aria-hidden="true" />
          Patron ревью
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-admin-text">{{ activeModeConfig.title }}</h2>
      </div>

      <div class="grid gap-3 sm:grid-cols-4 xl:min-w-[720px]">
        <div class="rounded-lg border border-admin-border bg-admin-surface p-4">
          <p class="text-xs uppercase tracking-wide text-admin-text-faint">Всего</p>
          <p class="mt-2 text-2xl font-semibold text-admin-text">{{ stats.total }}</p>
        </div>
        <div class="rounded-lg border border-admin-border bg-admin-surface p-4">
          <p class="text-xs uppercase tracking-wide text-admin-text-faint">Осталось</p>
          <p class="mt-2 text-2xl font-semibold text-admin-text">{{ stats.remaining }}</p>
        </div>
        <div class="rounded-lg border border-admin-success-border bg-admin-success-soft p-4">
          <p class="text-xs uppercase tracking-wide text-admin-success">Прокликано</p>
          <p class="mt-2 text-2xl font-semibold text-admin-success">{{ stats.reviewed }}</p>
        </div>
        <div class="rounded-lg border border-admin-border bg-admin-surface-muted p-4">
          <p class="text-xs uppercase tracking-wide text-admin-text-faint">Скип</p>
          <p class="mt-2 text-2xl font-semibold text-admin-text">{{ stats.skipped }}</p>
        </div>
      </div>
    </div>

    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div class="inline-flex w-full rounded-md border border-admin-border bg-admin-surface p-1 sm:w-auto">
        <button
          v-for="mode in reviewModes"
          :key="mode.value"
          type="button"
          class="inline-flex h-9 flex-1 items-center justify-center rounded px-4 text-sm font-semibold transition sm:flex-none"
          :class="activeMode === mode.value
            ? 'bg-admin-text text-admin-surface'
            : 'text-admin-text-muted hover:bg-admin-surface-muted hover:text-admin-text'"
          :aria-pressed="activeMode === mode.value"
          @click="activeMode = mode.value"
        >
          {{ mode.label }}
        </button>
      </div>

      <div
        v-if="activeMode === 'patron_rejected'"
        class="flex flex-col gap-2 sm:flex-row sm:items-center"
      >
        <span class="text-xs font-semibold uppercase tracking-wide text-admin-text-faint">
          Уверенность
        </span>
        <div class="inline-flex rounded-md border border-admin-border bg-admin-surface p-1">
          <button
            v-for="threshold in probabilityThresholds"
            :key="threshold.value"
            type="button"
            class="inline-flex h-9 items-center justify-center rounded px-3 text-sm font-semibold transition"
            :class="minProbability === threshold.value
              ? 'bg-admin-text text-admin-surface'
              : 'text-admin-text-muted hover:bg-admin-surface-muted hover:text-admin-text'"
            :aria-pressed="minProbability === threshold.value"
            @click="minProbability = threshold.value"
          >
            {{ threshold.label }}
          </button>
        </div>
      </div>
    </div>

    <div class="h-2 overflow-hidden rounded-full bg-admin-surface-muted">
      <div
        class="h-full rounded-full bg-admin-link transition-all"
        :style="{ width: `${progressPercent}%` }"
      />
    </div>

    <div v-if="isLoading" class="rounded-lg border border-admin-border bg-admin-surface p-8 text-sm text-admin-text-muted">
      Загрузка...
    </div>

    <div v-else-if="!item" class="rounded-lg border border-admin-success-border bg-admin-success-soft p-8">
      <p class="text-lg font-semibold text-admin-success">Очередь пуста</p>
      <p class="mt-2 text-sm text-admin-text-muted">{{ activeModeConfig.empty }}</p>
      <button
        type="button"
        class="mt-5 inline-flex h-10 items-center gap-2 rounded-md border border-admin-border bg-admin-surface px-4 text-sm font-semibold text-admin-text transition hover:border-admin-border-strong"
        :disabled="busyAction === 'undo'"
        @click="undoPrevious"
      >
        <Icon :icon="icons.restore" class="size-4" aria-hidden="true" />
        Отменить предыдущий
      </button>
    </div>

    <div v-else class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <article class="space-y-5 rounded-lg border border-admin-border bg-admin-surface p-5">
        <div class="flex flex-col gap-4 lg:flex-row lg:items-start">
          <div class="flex min-h-44 items-center justify-center overflow-hidden rounded-lg border border-admin-border bg-admin-surface-muted lg:w-64">
            <img
              v-if="item.image_url"
              :src="item.image_url"
              :alt="item.title"
              class="h-full max-h-64 w-full object-cover"
            >
            <Icon v-else :icon="icons.package" class="size-12 text-admin-text-faint" aria-hidden="true" />
          </div>

          <div class="min-w-0 flex-1 space-y-3">
            <div class="flex flex-wrap gap-2">
              <span class="rounded-md border border-admin-border bg-admin-surface-muted px-2.5 py-1 text-xs font-semibold text-admin-text-muted">
                {{ item.source }}
              </span>
              <span class="rounded-md border border-admin-border bg-admin-surface-muted px-2.5 py-1 text-xs font-semibold text-admin-text-muted">
                {{ item.shop.name }}
              </span>
              <span class="rounded-md border border-admin-border bg-admin-surface-muted px-2.5 py-1 text-xs font-semibold text-admin-text-muted">
                {{ modelLabel }}
              </span>
            </div>

            <h3 class="text-2xl font-semibold leading-tight text-admin-text">{{ item.title }}</h3>
            <p class="text-sm text-admin-text-muted">{{ item.normalized_title }}</p>

            <p v-if="item.description" class="max-w-3xl text-sm leading-6 text-admin-text-muted">
              {{ item.description }}
            </p>

            <div class="grid gap-3 md:grid-cols-2">
              <div class="rounded-lg border border-admin-border bg-admin-bg p-4">
                <p class="text-xs uppercase tracking-wide text-admin-text-faint">Цена</p>
                <p class="mt-2 text-lg font-semibold text-admin-text">{{ formatPrice(item) }}</p>
              </div>
              <div class="rounded-lg border border-admin-border bg-admin-bg p-4">
                <p class="text-xs uppercase tracking-wide text-admin-text-faint">Категория</p>
                <p class="mt-2 text-lg font-semibold text-admin-text">
                  {{ item.category?.name ?? item.category_raw ?? 'Без категории' }}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div class="grid gap-3 md:grid-cols-3">
          <div class="rounded-lg border border-admin-border bg-admin-bg p-4">
            <p class="text-xs uppercase tracking-wide text-admin-text-faint">Вероятность “не товар”</p>
            <p class="mt-2 text-xl font-semibold text-admin-text">{{ probabilityLabel }}</p>
          </div>
          <div class="rounded-lg border border-admin-border bg-admin-bg p-4">
            <p class="text-xs uppercase tracking-wide text-admin-text-faint">Метод</p>
            <p class="mt-2 text-xl font-semibold text-admin-text">{{ methodLabel }}</p>
          </div>
          <div class="rounded-lg border border-admin-border bg-admin-bg p-4">
            <p class="text-xs uppercase tracking-wide text-admin-text-faint">Последнее наблюдение</p>
            <p class="mt-2 text-xl font-semibold text-admin-text">{{ formatDateTime(item.last_seen_at) }}</p>
          </div>
        </div>

        <div class="space-y-3">
          <p class="text-xs font-semibold uppercase tracking-wide text-admin-text-faint">Причины</p>
          <div class="flex flex-wrap gap-2">
            <span
              v-for="reviewReason in reasonList"
              :key="reviewReason"
              class="rounded-md border border-admin-border bg-admin-surface-muted px-3 py-1.5 text-xs font-medium text-admin-text-muted"
            >
              {{ reviewReason }}
            </span>
            <span v-if="!reasonList.length" class="text-sm text-admin-text-muted">Нет причин</span>
          </div>
        </div>

        <details class="rounded-lg border border-admin-border bg-admin-bg">
          <summary class="cursor-pointer px-4 py-3 text-sm font-semibold text-admin-text">
            Raw payload
          </summary>
          <pre class="max-h-96 overflow-auto border-t border-admin-border p-4 text-xs leading-5 text-admin-text-muted">{{ rawJson(item) }}</pre>
        </details>
      </article>

      <aside class="space-y-4">
        <div class="rounded-lg border border-admin-border bg-admin-surface p-4">
          <label class="block">
            <span class="text-xs font-semibold uppercase tracking-wide text-admin-text-faint">Комментарий</span>
            <textarea
              v-model="reason"
              rows="4"
              class="mt-2 w-full resize-none rounded-md border border-admin-border bg-admin-bg px-3 py-2 text-sm text-admin-text outline-none transition placeholder:text-admin-text-faint focus:border-admin-link"
              placeholder="Причина решения"
            />
          </label>
        </div>

        <div class="grid gap-3">
          <button
            type="button"
            class="inline-flex h-12 items-center justify-center gap-2 rounded-md border border-admin-success-border bg-admin-success-soft px-4 text-sm font-semibold text-admin-success transition hover:border-admin-success"
            :disabled="Boolean(busyAction)"
            @click="decide('product')"
          >
            <Icon :icon="icons.check" class="size-4" aria-hidden="true" />
            Товар
          </button>
          <button
            type="button"
            class="inline-flex h-12 items-center justify-center gap-2 rounded-md border border-admin-danger-border bg-admin-danger-soft px-4 text-sm font-semibold text-admin-danger transition hover:border-admin-danger"
            :disabled="Boolean(busyAction)"
            @click="decide('not_product')"
          >
            <Icon :icon="icons.x" class="size-4" aria-hidden="true" />
            Не товар
          </button>
          <button
            type="button"
            class="inline-flex h-12 items-center justify-center gap-2 rounded-md border border-admin-border bg-admin-surface px-4 text-sm font-semibold text-admin-text transition hover:border-admin-border-strong"
            :disabled="Boolean(busyAction)"
            @click="undoPrevious"
          >
            <Icon :icon="icons.restore" class="size-4" aria-hidden="true" />
            Отменить предыдущий
          </button>
          <button
            type="button"
            class="inline-flex h-12 items-center justify-center gap-2 rounded-md border border-admin-border bg-admin-surface-muted px-4 text-sm font-semibold text-admin-text-muted transition hover:border-admin-border-strong hover:text-admin-text"
            :disabled="Boolean(busyAction)"
            @click="decide('skip')"
          >
            <Icon :icon="icons.chevronRight" class="size-4" aria-hidden="true" />
            Скип
          </button>
        </div>

        <div class="rounded-lg border border-admin-border bg-admin-surface p-4 text-sm text-admin-text-muted">
          <dl class="space-y-3">
            <div>
              <dt class="text-xs uppercase tracking-wide text-admin-text-faint">ID</dt>
              <dd class="mt-1 text-admin-text">{{ item.id }}</dd>
            </div>
            <div>
              <dt class="text-xs uppercase tracking-wide text-admin-text-faint">Source product ID</dt>
              <dd class="mt-1 break-all text-admin-text">{{ item.source_product_id ?? '-' }}</dd>
            </div>
            <div>
              <dt class="text-xs uppercase tracking-wide text-admin-text-faint">Source updated</dt>
              <dd class="mt-1 text-admin-text">{{ formatDateTime(item.source_updated_at) }}</dd>
            </div>
          </dl>
          <RouterLink
            :to="`/products/${item.id}`"
            class="mt-4 inline-flex h-10 items-center justify-center gap-2 rounded-md border border-admin-border px-4 text-sm font-semibold text-admin-text transition hover:border-admin-border-strong"
          >
            <Icon :icon="icons.externalLink" class="size-4" aria-hidden="true" />
            Карточка
          </RouterLink>
        </div>
      </aside>
    </div>
  </section>
</template>
