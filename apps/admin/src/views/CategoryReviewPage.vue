<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import {
  fetchCategoryQuality,
  fetchShops,
  type CategoryQualityResponse,
  type ShopListItem,
  type UncategorizedCategoryGroup,
} from '../lib/api'

const selectedSource = ref('')
const selectedShopId = ref('')
const shops = ref<ShopListItem[]>([])
const quality = ref<CategoryQualityResponse | null>(null)
const isLoading = ref(false)
const errorMessage = ref('')
const copyMessage = ref('')

let qualityRequest: AbortController | null = null

const sourceOptions = computed(() => {
  return Array.from(new Set(shops.value.map((shop) => shop.source))).sort()
})

const filteredShopOptions = computed(() => {
  if (!selectedSource.value) {
    return shops.value
  }

  return shops.value.filter((shop) => shop.source === selectedSource.value)
})

const coveragePercent = computed(() => Number(quality.value?.coverage_pct || 0))

const exportText = computed(() => {
  if (!quality.value) {
    return ''
  }

  const lines = [
    'category quality summary:',
    `total_products=${quality.value.total_products}`,
    `categorized_products=${quality.value.categorized_products}`,
    `uncategorized_products=${quality.value.uncategorized_products}`,
    `coverage_pct=${quality.value.coverage_pct}`,
    '',
    'uncategorized groups:',
  ]

  for (const group of quality.value.groups) {
    lines.push(formatGroupForExport(group))
    for (const title of group.titles) {
      lines.push(`  title: ${title}`)
    }
  }

  return lines.join('\n')
})

function formatGroupForExport(group: UncategorizedCategoryGroup): string {
  return [
    'uncategorized group:',
    `source=${group.source}`,
    `shop_id=${group.shop_id}`,
    `shop_source_id=${group.shop_source_id}`,
    `shop_name=${group.shop_name}`,
    `category_raw=${group.category_raw || '-'}`,
    `count=${group.count}`,
  ].join(' ')
}

async function copyExportText(): Promise<void> {
  if (!exportText.value) {
    return
  }

  try {
    await navigator.clipboard.writeText(exportText.value)
    copyMessage.value = 'Скопировано для issue comment'
  } catch {
    copyMessage.value = 'Не удалось скопировать автоматически, текст ниже можно выделить вручную'
  }
  window.setTimeout(() => {
    copyMessage.value = ''
  }, 2200)
}

async function loadQuality(): Promise<void> {
  qualityRequest?.abort()
  const request = new AbortController()
  qualityRequest = request
  isLoading.value = true
  errorMessage.value = ''

  try {
    const [shopResponse, qualityResponse] = await Promise.all([
      fetchShops({}, request.signal),
      fetchCategoryQuality(
        {
          source: selectedSource.value,
          shopId: selectedShopId.value ? Number(selectedShopId.value) : undefined,
          limitGroups: 50,
          titlesPerGroup: 5,
        },
        request.signal,
      ),
    ])
    shops.value = shopResponse.items
    quality.value = qualityResponse
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }

    errorMessage.value =
      error instanceof Error ? error.message : 'Не удалось загрузить качество категорий'
    quality.value = null
  } finally {
    if (qualityRequest === request) {
      isLoading.value = false
    }
  }
}

watch(selectedSource, () => {
  if (selectedShopId.value) {
    const selectedShop = shops.value.find((shop) => String(shop.id) === selectedShopId.value)
    if (selectedSource.value && selectedShop && selectedShop.source !== selectedSource.value) {
      selectedShopId.value = ''
      return
    }
  }

  void loadQuality()
})

watch(selectedShopId, () => {
  void loadQuality()
})

onMounted(() => {
  void loadQuality()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 2xl:flex-row 2xl:items-end 2xl:justify-between">
      <div>
        <p class="text-sm font-medium text-amber-300">Качество категорий</p>
        <h2 class="mt-2 text-2xl font-semibold text-white">Проверка шумных категорий</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
          Группируем некатегоризованные товары по исходной категории и собираем примеры для правок.
        </p>
      </div>

      <div
        class="grid gap-3 sm:grid-cols-[minmax(160px,1fr)_minmax(220px,1.4fr)] 2xl:min-w-[560px]"
        data-testid="category-quality-filters"
      >
        <select
          v-model="selectedSource"
          aria-label="Фильтр качества категорий по источнику"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        >
          <option value="">Все источники</option>
          <option v-for="source in sourceOptions" :key="source" :value="source">
            {{ source }}
          </option>
        </select>
        <select
          v-model="selectedShopId"
          aria-label="Фильтр качества категорий по магазину"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        >
          <option value="">Все магазины</option>
          <option v-for="shop in filteredShopOptions" :key="shop.id" :value="String(shop.id)">
            {{ shop.name }} · {{ shop.source }}
          </option>
        </select>
      </div>
    </div>

    <div
      v-if="errorMessage"
      class="rounded-lg border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-100"
    >
      Не удалось загрузить качество категорий: {{ errorMessage }}
    </div>

    <div class="grid gap-4 md:grid-cols-4">
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="text-sm text-neutral-500">Всего товаров</p>
        <p class="mt-3 text-3xl font-semibold text-white">{{ quality?.total_products || 0 }}</p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="text-sm text-neutral-500">Покрытие</p>
        <p
          class="mt-3 text-3xl font-semibold"
          :class="coveragePercent < 90 ? 'text-amber-200' : 'text-white'"
        >
          {{ quality?.coverage_pct || '0.00' }}%
        </p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="text-sm text-neutral-500">Без категории</p>
        <p
          class="mt-3 text-3xl font-semibold"
          :class="(quality?.uncategorized_products || 0) > 0 ? 'text-red-200' : 'text-white'"
        >
          {{ quality?.uncategorized_products || 0 }}
        </p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="text-sm text-neutral-500">Групп на ревью</p>
        <p class="mt-3 text-3xl font-semibold text-white">{{ quality?.groups.length || 0 }}</p>
      </div>
    </div>

    <div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div class="overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900/40">
        <div class="border-b border-neutral-800 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Unmatched by source category
        </div>

        <div v-if="isLoading" class="px-4 py-14 text-center text-sm text-neutral-500">
          Загружаем группы...
        </div>

        <div
          v-else-if="!quality || quality.groups.length === 0"
          class="px-4 py-14 text-center text-sm text-neutral-500"
        >
          Некатегоризованных групп по этим фильтрам нет.
        </div>

        <div v-else class="divide-y divide-neutral-800">
          <div
            v-for="group in quality.groups"
            :key="`${group.source}:${group.shop_id}:${group.category_raw || '-'}`"
            class="p-4"
            data-testid="category-quality-group"
          >
            <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div class="min-w-0">
                <p class="truncate text-base font-semibold text-white" :title="group.category_raw || 'Без исходной категории'">
                  {{ group.category_raw || 'Без исходной категории' }}
                </p>
                <p class="mt-1 text-sm text-neutral-500">
                  {{ group.shop_name }} · {{ group.source }} · {{ group.shop_source_id }}
                </p>
              </div>
              <span class="w-fit rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-1 text-xs text-amber-200">
                {{ group.count }} товаров
              </span>
            </div>
            <ul class="mt-4 space-y-2">
              <li
                v-for="title in group.titles"
                :key="title"
                class="rounded-md bg-neutral-950/50 px-3 py-2 text-sm text-neutral-300"
              >
                {{ title }}
              </li>
            </ul>
          </div>
        </div>
      </div>

      <div class="space-y-3">
        <button
          class="h-10 w-full rounded-md border border-amber-400/40 bg-amber-400/10 px-3 text-sm font-medium text-amber-100 transition hover:border-amber-300 disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!exportText"
          type="button"
          @click="copyExportText"
        >
          Скопировать отчет
        </button>
        <p v-if="copyMessage" class="text-sm text-emerald-300">{{ copyMessage }}</p>
        <textarea
          class="min-h-[420px] w-full resize-y rounded-lg border border-neutral-800 bg-neutral-950 p-3 font-mono text-xs leading-5 text-neutral-300 outline-none focus:border-amber-400"
          readonly
          :value="exportText"
        />
      </div>
    </div>
  </section>
</template>
