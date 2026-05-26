<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { useToast } from '@nuxt/ui/composables'
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import {
  autoAcceptCatalogWorkflowItems,
  fetchCatalogWorkflowQueue,
  type CatalogWorkflowAutoAcceptResponse,
  type CatalogWorkflowQueueItem,
  type CatalogWorkflowQueueName,
  type CatalogWorkflowReason,
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

const route = useRoute()
const toast = useToast()
const items = ref<CatalogWorkflowQueueItem[]>([])
const total = ref(0)
const isLoading = ref(false)
const isBatching = ref(false)
const errorMessage = ref('')
const searchQuery = ref('')
const batchPreview = ref<CatalogWorkflowAutoAcceptResponse | null>(null)

const queue = computed<CatalogWorkflowQueueName>(() => {
  const value = Array.isArray(route.params.queue) ? route.params.queue[0] : route.params.queue
  return isQueueName(value) ? value : 'auto_acceptable'
})

const activeMeta = computed(() => {
  return queueMeta.find((item) => item.queue === queue.value) ?? queueMeta[0]
})

const canBatchAccept = computed(() => queue.value === 'auto_acceptable')

function isQueueName(value: unknown): value is CatalogWorkflowQueueName {
  return typeof value === 'string' && queueMeta.some((item) => item.queue === value)
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

async function loadQueue(): Promise<void> {
  isLoading.value = true
  errorMessage.value = ''
  batchPreview.value = null

  try {
    const response = await fetchCatalogWorkflowQueue(queue.value, {
      q: searchQuery.value,
      limit: 50,
      offset: 0,
    })
    items.value = response.items
    total.value = response.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Неизвестная ошибка'
    items.value = []
    total.value = 0
  } finally {
    isLoading.value = false
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

watch(queue, () => {
  void loadQueue()
})

onMounted(() => {
  void loadQueue()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
      <div>
        <p class="inline-flex items-center gap-2 text-sm font-medium text-amber-300">
          <Icon :icon="activeMeta.icon" class="size-4" aria-hidden="true" />
          {{ activeMeta.eyebrow }}
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-white">{{ activeMeta.label }}</h2>
        <p class="mt-2 text-sm leading-6 text-neutral-400">
          {{ isLoading ? 'Загрузка...' : `${total} карточек в текущей очереди` }}
        </p>
      </div>

      <div class="flex flex-col gap-2 sm:flex-row">
        <RouterLink
          to="/"
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-neutral-800 px-4 text-sm font-semibold text-neutral-300 transition hover:border-neutral-700 hover:text-white"
        >
          <Icon :icon="icons.layoutDashboard" class="size-4" aria-hidden="true" />
          Сводка
        </RouterLink>
        <button
          v-if="canBatchAccept"
          type="button"
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-amber-300 px-4 text-sm font-semibold text-neutral-950 transition hover:bg-amber-200 disabled:cursor-wait disabled:opacity-60"
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
        :class="queue === item.queue ? 'border-amber-300 bg-amber-300 text-neutral-950' : 'border-neutral-800 bg-neutral-900/40 text-neutral-300 hover:border-neutral-700 hover:text-white'"
      >
        <Icon :icon="item.icon" class="size-4" aria-hidden="true" />
        {{ item.label }}
      </RouterLink>
    </div>

    <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
      <div class="grid gap-3 sm:grid-cols-[1fr_auto]">
        <label class="relative block">
          <Icon :icon="icons.search" class="pointer-events-none absolute left-3 top-3 size-4 text-neutral-600" aria-hidden="true" />
          <input
            v-model="searchQuery"
            type="search"
            class="h-10 w-full rounded-md border border-neutral-800 bg-neutral-950 pl-9 pr-3 text-sm text-white outline-none transition placeholder:text-neutral-600 focus:border-amber-400"
            placeholder="Поиск по названию"
            aria-label="Поиск по названию"
            @keyup.enter="loadQueue"
          >
        </label>
        <button
          type="button"
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-neutral-700 px-4 text-sm font-semibold text-neutral-200 transition hover:border-amber-300 hover:text-amber-100"
          @click="loadQueue"
        >
          <Icon :icon="icons.filter" class="size-4" aria-hidden="true" />
          Найти
        </button>
      </div>
    </div>

    <div
      v-if="batchPreview"
      class="rounded-lg border border-amber-400/30 bg-amber-400/10 p-4"
    >
      <div class="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div class="grid gap-3 sm:grid-cols-3">
          <div>
            <p class="text-xs uppercase tracking-wide text-amber-200/80">На странице</p>
            <p class="mt-1 text-xl font-semibold text-amber-50">{{ batchPreview.page_size }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-amber-200/80">Принять</p>
            <p class="mt-1 text-xl font-semibold text-amber-50">{{ batchPreview.would_accept }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-amber-200/80">Пропустить</p>
            <p class="mt-1 text-xl font-semibold text-amber-50">{{ batchPreview.skipped }}</p>
          </div>
        </div>

        <button
          type="button"
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-amber-300 px-4 text-sm font-semibold text-neutral-950 transition hover:bg-amber-200 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="isBatching || batchPreview.would_accept === 0"
          @click="applyBatchAccept"
        >
          <Icon :icon="icons.check" class="size-4" aria-hidden="true" />
          {{ isBatching ? 'Применяем...' : `Принять ${batchPreview.would_accept}` }}
        </button>
      </div>
    </div>

    <div
      v-if="errorMessage"
      class="rounded-lg border border-red-400/30 bg-red-400/10 p-4 text-sm text-red-100"
    >
      {{ errorMessage }}
    </div>

    <div v-if="isLoading" class="grid gap-3">
      <div
        v-for="index in 4"
        :key="index"
        class="h-32 animate-pulse rounded-lg border border-neutral-800 bg-neutral-900/40"
      />
    </div>

    <div
      v-else-if="items.length === 0 && !errorMessage"
      class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-6 text-sm text-neutral-400"
    >
      {{ activeMeta.empty }}
    </div>

    <div v-else class="grid gap-3">
      <article
        v-for="item in items"
        :key="item.id"
        class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4"
      >
        <div class="grid gap-4 xl:grid-cols-[1fr_280px]">
          <div>
            <div class="flex flex-wrap items-center gap-2">
              <span class="rounded-md border border-neutral-700 px-2 py-1 text-xs font-medium text-neutral-300">
                {{ item.source }}
              </span>
              <span class="text-xs text-neutral-500">{{ item.shop.name }}</span>
              <span class="text-xs text-neutral-600">{{ formatDateTime(item.last_seen_at) }}</span>
            </div>
            <h3 class="mt-3 text-base font-semibold text-white">{{ item.title }}</h3>
            <p class="mt-1 text-sm text-neutral-500">{{ item.normalized_title }}</p>
            <div class="mt-3 flex flex-wrap gap-2 text-xs text-neutral-300">
              <span class="rounded-md border border-neutral-800 bg-neutral-950 px-2 py-1">
                {{ item.category?.name ?? item.category_raw ?? 'Без категории' }}
              </span>
              <span class="rounded-md border border-neutral-800 bg-neutral-950 px-2 py-1">
                {{ formatPrice(item) }}
              </span>
              <span
                v-if="primaryReason(item)"
                class="rounded-md border border-neutral-800 bg-neutral-950 px-2 py-1"
              >
                {{ actionLabel(primaryReason(item)?.action ?? null) }}
              </span>
            </div>
          </div>

          <div class="rounded-md border border-neutral-800 bg-neutral-950 p-3">
            <p class="text-xs uppercase tracking-wide text-neutral-600">Сигнал</p>
            <p class="mt-2 text-sm text-neutral-200">
              {{ primaryReason(item) ? reasonText(primaryReason(item)!) : 'Нет данных пайплайна' }}
            </p>
            <RouterLink
              :to="`/products/${item.id}`"
              class="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-amber-200 hover:text-amber-100"
            >
              Открыть карточку
              <Icon :icon="icons.chevronRight" class="size-4" aria-hidden="true" />
            </RouterLink>
          </div>
        </div>

        <div v-if="item.candidate_matches.length" class="mt-4 grid gap-2">
          <div
            v-for="match in item.candidate_matches"
            :key="match.id"
            class="rounded-md border border-neutral-800 bg-neutral-950 p-3"
          >
            <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p class="text-sm font-semibold text-white">{{ match.canonical_title }}</p>
                <p class="mt-1 text-xs text-neutral-500">{{ match.method }} · {{ match.confidence }}</p>
              </div>
              <RouterLink
                :to="`/canonical-products/${match.canonical_product_id}`"
                class="inline-flex h-8 items-center justify-center gap-2 rounded-md border border-neutral-700 px-3 text-sm font-semibold text-neutral-300 transition hover:border-neutral-600 hover:text-white"
              >
                <Icon :icon="icons.tags" class="size-4" aria-hidden="true" />
                Каталог
              </RouterLink>
            </div>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>
