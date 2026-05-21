<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  fetchProductPriceHistory,
  fetchProducts,
  type ProductPriceSnapshot,
  type ProductSearchItem,
} from '../lib/api'

const route = useRoute()
const router = useRouter()

const productQuery = ref('')
const selectedProductId = ref('')
const products = ref<ProductSearchItem[]>([])
const snapshots = ref<ProductPriceSnapshot[]>([])
const selectedProduct = ref<ProductSearchItem | null>(null)
const isLoadingProducts = ref(false)
const isLoadingHistory = ref(false)
const productErrorMessage = ref('')
const historyErrorMessage = ref('')

let productRequest: AbortController | null = null
let historyRequest: AbortController | null = null
let productSearchTimer: number | undefined

const selectedProductIdNumber = computed(() => {
  const parsed = Number(selectedProductId.value)
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

function formatPrice(snapshot: ProductPriceSnapshot): string {
  if (snapshot.price === null) {
    return 'Цена отсутствует'
  }

  const amount = Number(snapshot.price)
  const value = Number.isFinite(amount)
    ? new Intl.NumberFormat('ru-RU', {
        maximumFractionDigits: 2,
        minimumFractionDigits: amount % 1 === 0 ? 0 : 2,
      }).format(amount)
    : snapshot.price
  const unit = snapshot.unit_raw ? ` / ${snapshot.unit_raw}` : ''

  return `${value} ${snapshot.currency}${unit}`
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

function selectProductFromList(productId: string): void {
  const product = products.value.find((item) => String(item.id) === productId)
  selectedProduct.value = product || null
}

async function loadProducts(): Promise<void> {
  productRequest?.abort()
  const request = new AbortController()
  productRequest = request
  isLoadingProducts.value = true
  productErrorMessage.value = ''

  try {
    const response = await fetchProducts(
      {
        q: productQuery.value,
        sort: '-last_seen_at',
        limit: 25,
        offset: 0,
      },
      request.signal,
    )
    products.value = response.items
    if (selectedProductId.value) {
      selectProductFromList(selectedProductId.value)
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }

    productErrorMessage.value =
      error instanceof Error ? error.message : 'Не удалось загрузить список товаров'
    products.value = []
  } finally {
    if (productRequest === request) {
      isLoadingProducts.value = false
    }
  }
}

async function loadHistory(productId: number): Promise<void> {
  historyRequest?.abort()
  const request = new AbortController()
  historyRequest = request
  isLoadingHistory.value = true
  historyErrorMessage.value = ''

  try {
    const response = await fetchProductPriceHistory(productId, request.signal)
    snapshots.value = response.items
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }

    historyErrorMessage.value =
      error instanceof Error ? error.message : 'Не удалось загрузить историю цен'
    snapshots.value = []
  } finally {
    if (historyRequest === request) {
      isLoadingHistory.value = false
    }
  }
}

watch(productQuery, () => {
  window.clearTimeout(productSearchTimer)
  productSearchTimer = window.setTimeout(() => {
    void loadProducts()
  }, 250)
})

watch(selectedProductId, (productId) => {
  selectProductFromList(productId)

  void router.replace({
    name: 'prices',
    query: productId ? { productId, q: productQuery.value || undefined } : {},
  })

  const parsed = selectedProductIdNumber.value
  if (parsed === null) {
    snapshots.value = []
    historyErrorMessage.value = ''
    return
  }

  void loadHistory(parsed)
})

watch(
  () => route.query.productId,
  (productId) => {
    const nextProductId = Array.isArray(productId) ? productId[0] : productId
    selectedProductId.value = nextProductId || ''
  },
)

onMounted(() => {
  const initialProductId = route.query.productId
  const initialQuery = route.query.q
  productQuery.value = Array.isArray(initialQuery) ? initialQuery[0] || '' : initialQuery || ''
  selectedProductId.value = Array.isArray(initialProductId) ? initialProductId[0] || '' : initialProductId || ''
  window.clearTimeout(productSearchTimer)
  void loadProducts()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 2xl:flex-row 2xl:items-end 2xl:justify-between">
      <div>
        <p class="text-sm font-medium text-amber-300">История цен</p>
        <h2 class="mt-2 text-2xl font-semibold text-white">Наблюдения по товару во времени</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
          Выберите исходную карточку из каталога, чтобы посмотреть повторные наблюдения и время сбора.
        </p>
      </div>

      <div
        class="grid gap-3 lg:grid-cols-[minmax(220px,1.2fr)_minmax(280px,1.8fr)] 2xl:min-w-[720px]"
        data-testid="price-history-picker"
      >
        <input
          v-model="productQuery"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition placeholder:text-neutral-600 focus:border-amber-400"
          placeholder="Поиск карточки"
          type="search"
        />
        <select
          v-model="selectedProductId"
          aria-label="Исходная карточка для истории цен"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
          :disabled="isLoadingProducts"
        >
          <option value="">Выберите товар</option>
          <option v-for="product in products" :key="product.id" :value="String(product.id)">
            #{{ product.id }} · {{ product.title }} · {{ product.shop.name }}
          </option>
        </select>
      </div>
    </div>

    <div
      v-if="productErrorMessage"
      class="rounded-lg border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-100"
    >
      Список товаров не загрузился: {{ productErrorMessage }}
    </div>

    <div
      v-if="selectedProductId"
      class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]"
      data-testid="price-history-detail"
    >
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="text-xs font-semibold uppercase tracking-wide text-neutral-500">Исходная карточка</p>
        <h3 class="mt-3 text-lg font-semibold text-white">
          {{ selectedProduct?.title || `Карточка #${selectedProductId}` }}
        </h3>
        <div class="mt-4 grid gap-3 text-sm text-neutral-400 sm:grid-cols-2">
          <div>
            <p class="text-xs uppercase tracking-wide text-neutral-600">Магазин</p>
            <p class="mt-1 text-neutral-200">{{ selectedProduct?.shop.name || '-' }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-neutral-600">Source ID</p>
            <p class="mt-1 text-neutral-200">
              {{ selectedProduct?.source_product_id || selectedProductId }}
            </p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-neutral-600">Категория источника</p>
            <p class="mt-1 text-neutral-200">{{ selectedProduct?.category_raw || '-' }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-neutral-600">Последний раз</p>
            <p class="mt-1 text-neutral-200">
              {{ selectedProduct ? formatDateTime(selectedProduct.last_seen_at) : '-' }}
            </p>
          </div>
        </div>
      </div>

      <div class="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
        <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
          <p class="text-xs uppercase tracking-wide text-neutral-500">Наблюдений</p>
          <p class="mt-2 text-2xl font-semibold text-white">{{ snapshots.length }}</p>
        </div>
        <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
          <p class="text-xs uppercase tracking-wide text-neutral-500">Повторов цены</p>
          <p class="mt-2 text-2xl font-semibold text-white">{{ repeatedObservations }}</p>
        </div>
        <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
          <p class="text-xs uppercase tracking-wide text-neutral-500">Без цены</p>
          <p class="mt-2 text-2xl font-semibold text-white">{{ nullPriceCount }}</p>
        </div>
      </div>
    </div>

    <div v-else class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-8 text-sm text-neutral-500">
      Найдите и выберите исходную карточку, чтобы открыть ее историю цен.
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
        Загружаем историю...
      </div>

      <div
        v-else-if="historyErrorMessage"
        class="min-w-[760px] px-4 py-14 text-center text-sm text-red-200"
      >
        Не удалось загрузить историю цен: {{ historyErrorMessage }}
      </div>

      <div
        v-else-if="selectedProductId && snapshots.length === 0"
        class="min-w-[760px] px-4 py-14 text-center text-sm text-neutral-500"
      >
        Для этой карточки пока нет ценовых наблюдений.
      </div>

      <div
        v-else-if="!selectedProductId"
        class="min-w-[760px] px-4 py-14 text-center text-sm text-neutral-500"
      >
        История появится после выбора товара.
      </div>

      <div v-else class="min-w-[760px] divide-y divide-neutral-800">
        <div
          v-for="(snapshot, index) in snapshots"
          :key="snapshot.id"
          class="grid grid-cols-[190px_180px_150px_170px_minmax(160px,1fr)] px-4 py-4 text-sm"
          data-testid="price-snapshot-row"
        >
          <div class="text-neutral-200">{{ formatDateTime(snapshot.parsed_at) }}</div>
          <div class="font-medium text-white">{{ formatPrice(snapshot) }}</div>
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

    <p v-if="selectedProductId" class="text-sm text-neutral-500">
      Изменений цены: {{ priceChanges }}. Повторные наблюдения остаются видимыми, потому что snapshot
      хранит факт наблюдения, а не только изменение.
    </p>
  </section>
</template>
