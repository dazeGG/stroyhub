<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import {
  fetchCatalogWorkflowDashboard,
  type CatalogWorkflowDashboardCount,
  type CatalogWorkflowQueueName,
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
    label: 'Нужна проверка',
    detail: 'слабые или спорные сигналы',
    to: '/workflows/queues/review_needed',
    icon: icons.listCheck,
    tone: 'border-amber-400/30 bg-amber-400/10 text-amber-100',
  },
  {
    queue: 'possible_duplicates',
    label: 'Похожие товары',
    detail: 'нужно сверить похожие карточки',
    to: '/workflows/queues/possible_duplicates',
    icon: icons.gitCompare,
    tone: 'border-sky-400/30 bg-sky-400/10 text-sky-100',
  },
  {
    queue: 'data_problems',
    label: 'Проблемы данных',
    detail: 'не товар, ошибка пайплайна или плохие данные',
    to: '/workflows/queues/data_problems',
    icon: icons.alertTriangle,
    tone: 'border-red-400/30 bg-red-400/10 text-red-100',
  },
  {
    queue: 'normalized_items',
    label: 'В каталоге',
    detail: 'уже связаны с нормализованными товарами',
    to: '/workflows/queues/normalized_items',
    icon: icons.tags,
    tone: 'border-neutral-700 bg-neutral-900/70 text-neutral-100',
  },
]

const counts = ref<CatalogWorkflowDashboardCount[]>([])
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

async function loadDashboard(): Promise<void> {
  isLoading.value = true
  errorMessage.value = ''

  try {
    const response = await fetchCatalogWorkflowDashboard()
    counts.value = response.counts
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Неизвестная ошибка'
  } finally {
    isLoading.value = false
  }
}

onMounted(() => {
  void loadDashboard()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
      <div>
        <p class="inline-flex items-center gap-2 text-sm font-medium text-amber-300">
          <Icon :icon="icons.layoutDashboard" class="size-4" aria-hidden="true" />
          Качество каталога
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-white">Операционная сводка</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
          Очереди построены вокруг решений по карточкам: принять, проверить, связать похожие товары или убрать проблемы из потока.
        </p>
      </div>

      <RouterLink
        to="/workflows/queues/auto_acceptable"
        class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-amber-300 px-4 text-sm font-semibold text-neutral-950 transition hover:bg-amber-200"
      >
        <Icon :icon="icons.check" class="size-4" aria-hidden="true" />
        Открыть главную очередь
      </RouterLink>
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

    <div class="grid gap-3 lg:grid-cols-[1.1fr_1fr]">
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="text-xs uppercase tracking-wide text-neutral-500">В работе</p>
        <div class="mt-3 flex items-end gap-3">
          <p class="text-4xl font-semibold text-white">{{ isLoading ? '...' : activeWorkCount }}</p>
          <p class="pb-1 text-sm text-neutral-400">карточек ждут решения</p>
        </div>
      </div>

      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="text-xs uppercase tracking-wide text-neutral-500">Нормализовано</p>
        <div class="mt-3 flex items-end gap-3">
          <p class="text-4xl font-semibold text-white">
            {{ isLoading ? '...' : (countByQueue.normalized_items ?? 0) }}
          </p>
          <p class="pb-1 text-sm text-neutral-400">связанных офферов</p>
        </div>
      </div>
    </div>

    <div class="grid gap-3 xl:grid-cols-5">
      <RouterLink
        v-for="item in queueMeta"
        :key="item.queue"
        :to="item.to"
        class="group rounded-lg border p-4 transition hover:-translate-y-0.5 hover:border-amber-300/50"
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

    <div
      v-if="!isLoading && !errorMessage && activeWorkCount === 0"
      class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-6 text-sm text-neutral-400"
    >
      Активных очередей нет.
    </div>
  </section>
</template>
