<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import {
  fetchProduct,
  fetchProductPriceHistory,
  type ProductPriceSnapshot,
  type ProductSearchItem,
} from '../lib/api'
import { icons } from '../lib/icons'

const route = useRoute()

const product = ref<ProductSearchItem | null>(null)
const snapshots = ref<ProductPriceSnapshot[]>([])
const isLoadingProduct = ref(false)
const isLoadingHistory = ref(false)
const productErrorMessage = ref('')
const historyErrorMessage = ref('')

let productRequest: AbortController | null = null
let historyRequest: AbortController | null = null

const productId = computed(() => {
  const rawValue = Array.isArray(route.params.productId)
    ? route.params.productId[0]
    : route.params.productId
  const parsed = Number(rawValue)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
})

const priceChanges = computed(() => {
  let changes = 0
  let previousPriceKey: string | null = null

  for (const snapshot of snapshots.value) {
    const priceKey = priceStateKey(snapshot)
    if (previousPriceKey !== null && priceKey !== previousPriceKey) {
      changes += 1
    }
    previousPriceKey = priceKey
  }

  return changes
})

const repeatedObservations = computed(() => {
  let repeated = 0
  let previousPriceKey: string | null = null

  for (const snapshot of snapshots.value) {
    const priceKey = priceStateKey(snapshot)
    if (previousPriceKey !== null && priceKey === previousPriceKey) {
      repeated += 1
    }
    previousPriceKey = priceKey
  }

  return repeated
})

const nullPriceCount = computed(() => snapshots.value.filter((snapshot) => snapshot.price === null).length)

function priceStateKey(snapshot: ProductPriceSnapshot): string {
  return snapshot.price === null ? 'null' : `${snapshot.price}:${snapshot.currency}:${snapshot.unit_raw || ''}`
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

function formatSnapshotPrice(snapshot: ProductPriceSnapshot): string {
  if (snapshot.price === null) {
    return 'Цена отсутствует'
  }

  return formatMoney(snapshot.price, snapshot.currency, snapshot.unit_raw)
}

function formatLatestPrice(item: ProductSearchItem | null): string {
  if (!item?.latest_price?.price) {
    return '-'
  }

  return formatMoney(item.latest_price.price, item.latest_price.currency, item.latest_price.unit_raw)
}

function formatMoney(price: string, currency: string, unitRaw: string | null): string {
  const amount = Number(price)
  const value = Number.isFinite(amount)
    ? new Intl.NumberFormat('ru-RU', {
        maximumFractionDigits: 2,
        minimumFractionDigits: amount % 1 === 0 ? 0 : 2,
      }).format(amount)
    : price
  const unit = unitRaw ? ` / ${unitRaw}` : ''

  return `${value} ${currency}${unit}`
}

function snapshotStatus(snapshot: ProductPriceSnapshot, index: number): string {
  if (snapshot.price === null) {
    return 'Нет цены'
  }

  if (index === 0) {
    return 'Первое наблюдение'
  }

  return priceStateKey(snapshot) === priceStateKey(snapshots.value[index - 1])
    ? 'Повтор цены'
    : 'Цена изменилась'
}

async function loadProduct(nextProductId: number): Promise<void> {
  productRequest?.abort()
  const request = new AbortController()
  productRequest = request
  isLoadingProduct.value = true
  productErrorMessage.value = ''

  try {
    product.value = await fetchProduct(nextProductId, request.signal)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }

    productErrorMessage.value = error instanceof Error ? error.message : 'Не удалось загрузить товар'
    product.value = null
  } finally {
    if (productRequest === request) {
      isLoadingProduct.value = false
    }
  }
}

async function loadHistory(nextProductId: number): Promise<void> {
  historyRequest?.abort()
  const request = new AbortController()
  historyRequest = request
  isLoadingHistory.value = true
  historyErrorMessage.value = ''

  try {
    const response = await fetchProductPriceHistory(nextProductId, request.signal)
    snapshots.value = response.items
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }

    historyErrorMessage.value = error instanceof Error ? error.message : 'Не удалось загрузить историю цен'
    snapshots.value = []
  } finally {
    if (historyRequest === request) {
      isLoadingHistory.value = false
    }
  }
}

function loadPage(): void {
  const nextProductId = productId.value
  if (nextProductId === null) {
    product.value = null
    snapshots.value = []
    productErrorMessage.value = 'Некорректный ID товара'
    historyErrorMessage.value = ''
    return
  }

  void loadProduct(nextProductId)
  void loadHistory(nextProductId)
}

watch(productId, () => {
  loadPage()
})

onMounted(() => {
  loadPage()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <RouterLink
          to="/"
          class="inline-flex items-center gap-2 text-sm font-medium text-neutral-400 transition hover:text-white"
        >
          <Icon :icon="icons.chevronLeft" class="size-4" aria-hidden="true" />
          Назад в каталог
        </RouterLink>
        <p class="mt-4 inline-flex items-center gap-2 text-sm font-medium text-amber-300">
          <Icon :icon="icons.package" class="size-4" aria-hidden="true" />
          Карточка товара
        </p>
        <h2 class="mt-2 max-w-4xl text-2xl font-semibold text-white">
          {{ product?.title || (productId ? `Товар #${productId}` : 'Товар') }}
        </h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
          Магазин, исходная категория, последняя цена и наблюдения по сбору.
        </p>
      </div>
    </div>

    <div
      v-if="productErrorMessage"
      class="rounded-lg border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-100"
    >
      Товар не загрузился: {{ productErrorMessage }}
    </div>

    <div
      v-if="product || isLoadingProduct"
      class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]"
      data-testid="product-detail"
    >
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
          <Icon :icon="icons.package" class="size-4" aria-hidden="true" />
          Исходная карточка
        </p>
        <div v-if="isLoadingProduct" class="mt-6 text-sm text-neutral-500">Загружаем товар...</div>
        <div v-else class="mt-4 grid gap-4 text-sm text-neutral-400 sm:grid-cols-2">
          <div>
            <p class="text-xs uppercase tracking-wide text-neutral-600">Магазин</p>
            <p class="mt-1 text-neutral-200">{{ product?.shop.name || '-' }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-neutral-600">Текущая цена</p>
            <p class="mt-1 text-neutral-200">{{ formatLatestPrice(product) }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-neutral-600">Source ID</p>
            <p class="mt-1 text-neutral-200">{{ product?.source_product_id || '-' }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-neutral-600">Источник</p>
            <p class="mt-1 text-neutral-200">{{ product?.source || '-' }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-neutral-600">Категория источника</p>
            <p class="mt-1 text-neutral-200">{{ product?.category_raw || '-' }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-neutral-600">Последний раз</p>
            <p class="mt-1 text-neutral-200">{{ formatDateTime(product?.last_seen_at || null) }}</p>
          </div>
        </div>
      </div>

      <div class="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
        <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
          <p class="inline-flex items-center gap-2 text-xs uppercase tracking-wide text-neutral-500">
            <Icon :icon="icons.timeline" class="size-4" aria-hidden="true" />
            Наблюдений
          </p>
          <p class="mt-2 text-2xl font-semibold text-white">{{ snapshots.length }}</p>
        </div>
        <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
          <p class="inline-flex items-center gap-2 text-xs uppercase tracking-wide text-neutral-500">
            <Icon :icon="icons.currencyRubel" class="size-4" aria-hidden="true" />
            Повторов цены
          </p>
          <p class="mt-2 text-2xl font-semibold text-white">{{ repeatedObservations }}</p>
        </div>
        <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
          <p class="inline-flex items-center gap-2 text-xs uppercase tracking-wide text-neutral-500">
            <Icon :icon="icons.alertTriangle" class="size-4" aria-hidden="true" />
            Без цены
          </p>
          <p class="mt-2 text-2xl font-semibold text-white">{{ nullPriceCount }}</p>
        </div>
      </div>
    </div>

    <div class="overflow-x-auto rounded-lg border border-neutral-800 bg-neutral-900/40">
      <div
        class="grid min-w-[760px] grid-cols-[190px_180px_150px_170px_minmax(160px,1fr)] border-b border-neutral-800 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neutral-500"
      >
        <span>Parsed at</span>
        <span>Цена</span>
        <span>Статус</span>
        <span>Source updated</span>
        <span>Snapshot ID</span>
      </div>

      <div v-if="isLoadingHistory" class="min-w-[760px] px-4 py-14 text-center text-sm text-neutral-500">
        <Icon :icon="icons.history" class="mx-auto mb-3 size-6 text-neutral-600" aria-hidden="true" />
        Загружаем историю...
      </div>

      <div
        v-else-if="historyErrorMessage"
        class="min-w-[760px] px-4 py-14 text-center text-sm text-red-200"
      >
        <Icon :icon="icons.alertTriangle" class="mx-auto mb-3 size-6 text-red-300" aria-hidden="true" />
        Не удалось загрузить историю цен: {{ historyErrorMessage }}
      </div>

      <div
        v-else-if="snapshots.length === 0"
        class="min-w-[760px] px-4 py-14 text-center text-sm text-neutral-500"
      >
        <Icon :icon="icons.timeline" class="mx-auto mb-3 size-6 text-neutral-600" aria-hidden="true" />
        Для этой карточки пока нет ценовых наблюдений.
      </div>

      <div v-else class="min-w-[760px] divide-y divide-neutral-800">
        <div
          v-for="(snapshot, index) in snapshots"
          :key="snapshot.id"
          class="grid grid-cols-[190px_180px_150px_170px_minmax(160px,1fr)] px-4 py-4 text-sm"
          data-testid="price-snapshot-row"
        >
          <div class="text-neutral-200">{{ formatDateTime(snapshot.parsed_at) }}</div>
          <div class="font-medium text-white">{{ formatSnapshotPrice(snapshot) }}</div>
          <div>
            <span
              class="rounded-full border px-2 py-1 text-xs"
              :class="
                snapshot.price === null
                  ? 'border-red-400/30 bg-red-400/10 text-red-200'
                  : snapshotStatus(snapshot, index) === 'Цена изменилась'
                    ? 'border-amber-400/30 bg-amber-400/10 text-amber-200'
                    : 'border-neutral-700 bg-neutral-900 text-neutral-300'
              "
            >
              {{ snapshotStatus(snapshot, index) }}
            </span>
          </div>
          <div class="text-neutral-400">{{ formatDateTime(snapshot.source_updated_at) }}</div>
          <div class="text-neutral-500">#{{ snapshot.id }}</div>
        </div>
      </div>
    </div>

    <p v-if="productId" class="text-sm text-neutral-500">
      Изменений цены: {{ priceChanges }}.
    </p>
  </section>
</template>
