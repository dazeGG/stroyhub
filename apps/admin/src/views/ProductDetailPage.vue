<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { useToast } from '@nuxt/ui/composables'
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import {
  assignProductCategoryOverride,
  fetchCategories,
  fetchProduct,
  fetchProductPriceHistory,
  revertProductCategoryOverride,
  type CategoryTreeItem,
  type ProductPriceSnapshot,
  type ProductSearchItem,
} from '../lib/api'
import { icons } from '../lib/icons'
import { messageFromError, toastError, toastSuccess } from '../lib/notifications'

const route = useRoute()
const toast = useToast()

const product = ref<ProductSearchItem | null>(null)
const categories = ref<CategoryTreeItem[]>([])
const snapshots = ref<ProductPriceSnapshot[]>([])
const selectedCategoryId = ref('')
const isLoadingProduct = ref(false)
const isLoadingCategories = ref(false)
const isLoadingHistory = ref(false)
const isSavingCategory = ref(false)
const productErrorMessage = ref('')
const categoryErrorMessage = ref('')
const historyErrorMessage = ref('')

let productRequest: AbortController | null = null
let historyRequest: AbortController | null = null
let categorySaveRequest: AbortController | null = null

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

const leafCategoryOptions = computed(() => {
  const options: { id: number; label: string }[] = []

  function walk(items: CategoryTreeItem[], path: string[]): void {
    for (const item of items) {
      const nextPath = [...path, item.name]
      if (item.children.length === 0) {
        options.push({ id: item.id, label: nextPath.join(' / ') })
      } else {
        walk(item.children, nextPath)
      }
    }
  }

  walk(categories.value, [])
  return options
})

const categoryNameById = computed(() => {
  const names = new Map<number, string>()

  function walk(items: CategoryTreeItem[]): void {
    for (const item of items) {
      names.set(item.id, item.name)
      walk(item.children)
    }
  }

  walk(categories.value)
  return names
})

const categoryLabel = computed(() => {
  if (!product.value?.category_id) {
    return 'Не нормализовано'
  }

  return categoryNameById.value.get(product.value.category_id) || `ID ${product.value.category_id}`
})

const hasActiveOverride = computed(() => product.value?.category_override != null)

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
    selectedCategoryId.value = product.value.category_id ? String(product.value.category_id) : ''
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }

    productErrorMessage.value = messageFromError(error, 'Не удалось загрузить товар')
    toastError(toast, 'Не удалось загрузить товар', error, 'Не удалось загрузить товар')
    product.value = null
  } finally {
    if (productRequest === request) {
      isLoadingProduct.value = false
    }
  }
}

async function loadCategories(): Promise<void> {
  isLoadingCategories.value = true
  categoryErrorMessage.value = ''

  try {
    const response = await fetchCategories()
    categories.value = response.items
  } catch (error) {
    categoryErrorMessage.value = messageFromError(error, 'Не удалось загрузить категории')
    toastError(toast, 'Не удалось загрузить категории', error, 'Не удалось загрузить категории')
  } finally {
    isLoadingCategories.value = false
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

    historyErrorMessage.value = messageFromError(error, 'Не удалось загрузить историю цен')
    toastError(toast, 'Не удалось загрузить историю цен', error, 'Не удалось загрузить историю цен')
    snapshots.value = []
  } finally {
    if (historyRequest === request) {
      isLoadingHistory.value = false
    }
  }
}

async function saveCategoryOverride(): Promise<void> {
  const nextProductId = productId.value
  const nextCategoryId = Number(selectedCategoryId.value)
  if (nextProductId === null || !Number.isInteger(nextCategoryId) || nextCategoryId <= 0) {
    return
  }

  categorySaveRequest?.abort()
  const request = new AbortController()
  categorySaveRequest = request
  isSavingCategory.value = true
  categoryErrorMessage.value = ''

  try {
    product.value = await assignProductCategoryOverride(nextProductId, nextCategoryId, request.signal)
    selectedCategoryId.value = product.value.category_id ? String(product.value.category_id) : ''
    toastSuccess(toast, 'Категория сохранена')
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }

    categoryErrorMessage.value = messageFromError(error, 'Не удалось сохранить категорию')
    toastError(toast, 'Не удалось сохранить категорию', error, 'Не удалось сохранить категорию')
  } finally {
    if (categorySaveRequest === request) {
      isSavingCategory.value = false
    }
  }
}

async function revertCategoryOverride(): Promise<void> {
  const nextProductId = productId.value
  if (nextProductId === null) {
    return
  }

  categorySaveRequest?.abort()
  const request = new AbortController()
  categorySaveRequest = request
  isSavingCategory.value = true
  categoryErrorMessage.value = ''

  try {
    product.value = await revertProductCategoryOverride(nextProductId, request.signal)
    selectedCategoryId.value = product.value.category_id ? String(product.value.category_id) : ''
    toastSuccess(toast, 'Категория откатана')
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }

    categoryErrorMessage.value = messageFromError(error, 'Не удалось откатить категорию')
    toastError(toast, 'Не удалось откатить категорию', error, 'Не удалось откатить категорию')
  } finally {
    if (categorySaveRequest === request) {
      isSavingCategory.value = false
    }
  }
}

function loadPage(): void {
  const nextProductId = productId.value
  if (nextProductId === null) {
    product.value = null
    snapshots.value = []
    productErrorMessage.value = 'Некорректный ID товара'
    toastError(toast, 'Некорректный ID товара', new Error(productErrorMessage.value), productErrorMessage.value)
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
  void loadCategories()
  loadPage()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <RouterLink
          to="/products"
          class="inline-flex items-center gap-2 text-sm font-medium text-admin-text-muted transition hover:text-admin-text"
        >
          <Icon :icon="icons.chevronLeft" class="size-4" aria-hidden="true" />
          Назад к исходным товарам
        </RouterLink>
        <p class="mt-4 inline-flex items-center gap-2 text-sm font-medium text-admin-link">
          <Icon :icon="icons.package" class="size-4" aria-hidden="true" />
          Карточка товара
        </p>
        <h2 class="mt-2 max-w-4xl text-2xl font-semibold text-admin-text">
          {{ product?.title || (productId ? `Товар #${productId}` : 'Товар') }}
        </h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-admin-text-muted">
          Магазин, исходная категория, последняя цена и наблюдения по сбору.
        </p>
      </div>
    </div>

    <div
      v-if="product || isLoadingProduct"
      class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]"
      data-testid="product-detail"
    >
      <div class="rounded-lg border border-admin-border bg-admin-surface p-5">
        <p class="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-admin-text-faint">
          <Icon :icon="icons.package" class="size-4" aria-hidden="true" />
          Исходная карточка
        </p>
        <div v-if="isLoadingProduct" class="mt-6 text-sm text-admin-text-faint">Загружаем товар...</div>
        <div v-else class="mt-4 grid gap-4 text-sm text-admin-text-muted sm:grid-cols-2">
          <div>
            <p class="text-xs uppercase tracking-wide text-admin-text-faint">Магазин</p>
            <p class="mt-1 text-admin-text">{{ product?.shop.name || '-' }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-admin-text-faint">Текущая цена</p>
            <p class="mt-1 text-admin-text">{{ formatLatestPrice(product) }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-admin-text-faint">Source ID</p>
            <p class="mt-1 text-admin-text">{{ product?.source_product_id || '-' }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-admin-text-faint">Источник</p>
            <p class="mt-1 text-admin-text">{{ product?.source || '-' }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-admin-text-faint">Категория источника</p>
            <p class="mt-1 text-admin-text">{{ product?.category_raw || '-' }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-admin-text-faint">Категория StroyHub</p>
            <p class="mt-1 text-admin-text">{{ categoryLabel }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-admin-text-faint">Последний раз</p>
            <p class="mt-1 text-admin-text">{{ formatDateTime(product?.last_seen_at || null) }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-admin-text-faint">Ручное правило</p>
            <p class="mt-1">
              <span
                class="rounded-full border px-2 py-1 text-xs"
                :class="
                  hasActiveOverride
                    ? 'border-admin-border-strong bg-admin-surface-muted text-admin-link'
                    : 'border-admin-border-strong bg-admin-surface-muted text-admin-text-muted'
                "
              >
                {{ hasActiveOverride ? 'Активен' : 'Нет' }}
              </span>
            </p>
          </div>
        </div>

        <div class="mt-6 border-t border-admin-border pt-5">
          <p class="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-admin-text-faint">
            <Icon :icon="icons.category" class="size-4" aria-hidden="true" />
            Ручная категория
          </p>
          <div class="mt-3 grid gap-3 md:grid-cols-[minmax(220px,1fr)_auto_auto]">
            <select
              v-model="selectedCategoryId"
              aria-label="Ручная категория товара"
              class="h-10 rounded-md border border-admin-border bg-admin-surface px-3 text-sm text-admin-text outline-none transition focus:border-admin-focus"
              :disabled="isLoadingCategories || isSavingCategory || !product"
            >
              <option value="">Выберите категорию</option>
              <option v-for="category in leafCategoryOptions" :key="category.id" :value="String(category.id)">
                {{ category.label }}
              </option>
            </select>
            <button
              class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-admin-primary px-4 text-sm font-semibold text-admin-primary-text transition enabled:hover:bg-admin-primary-hover disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="!selectedCategoryId || isSavingCategory || !product"
              type="button"
              @click="saveCategoryOverride"
            >
              <Icon :icon="icons.check" class="size-4" aria-hidden="true" />
              Сохранить
            </button>
            <button
              class="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-admin-border px-4 text-sm font-medium text-admin-text transition enabled:hover:border-admin-border-strong disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="!hasActiveOverride || isSavingCategory || !product"
              type="button"
              @click="revertCategoryOverride"
            >
              <Icon :icon="icons.restore" class="size-4" aria-hidden="true" />
              Откатить
            </button>
          </div>
        </div>
      </div>

      <div class="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
        <div class="rounded-lg border border-admin-border bg-admin-surface p-4">
          <p class="inline-flex items-center gap-2 text-xs uppercase tracking-wide text-admin-text-faint">
            <Icon :icon="icons.timeline" class="size-4" aria-hidden="true" />
            Наблюдений
          </p>
          <p class="mt-2 text-2xl font-semibold text-admin-text">{{ snapshots.length }}</p>
        </div>
        <div class="rounded-lg border border-admin-border bg-admin-surface p-4">
          <p class="inline-flex items-center gap-2 text-xs uppercase tracking-wide text-admin-text-faint">
            <Icon :icon="icons.currencyRubel" class="size-4" aria-hidden="true" />
            Повторов цены
          </p>
          <p class="mt-2 text-2xl font-semibold text-admin-text">{{ repeatedObservations }}</p>
        </div>
        <div class="rounded-lg border border-admin-border bg-admin-surface p-4">
          <p class="inline-flex items-center gap-2 text-xs uppercase tracking-wide text-admin-text-faint">
            <Icon :icon="icons.alertTriangle" class="size-4" aria-hidden="true" />
            Без цены
          </p>
          <p class="mt-2 text-2xl font-semibold text-admin-text">{{ nullPriceCount }}</p>
        </div>
      </div>
    </div>

    <div class="overflow-x-auto rounded-lg border border-admin-border bg-admin-surface">
      <div
        class="grid min-w-[760px] grid-cols-[190px_180px_150px_170px_minmax(160px,1fr)] border-b border-admin-border px-4 py-3 text-xs font-semibold uppercase tracking-wide text-admin-text-faint"
      >
        <span>Parsed at</span>
        <span>Цена</span>
        <span>Статус</span>
        <span>Source updated</span>
        <span>Snapshot ID</span>
      </div>

      <div v-if="isLoadingHistory" class="min-w-[760px] px-4 py-14 text-center text-sm text-admin-text-faint">
        <Icon :icon="icons.history" class="mx-auto mb-3 size-6 text-admin-text-faint" aria-hidden="true" />
        Загружаем историю...
      </div>

      <div
        v-else-if="historyErrorMessage"
        class="min-w-[760px] px-4 py-14 text-center text-sm text-admin-danger"
      >
        <Icon :icon="icons.alertTriangle" class="mx-auto mb-3 size-6 text-admin-danger" aria-hidden="true" />
        Не удалось загрузить историю цен: {{ historyErrorMessage }}
      </div>

      <div
        v-else-if="snapshots.length === 0"
        class="min-w-[760px] px-4 py-14 text-center text-sm text-admin-text-faint"
      >
        <Icon :icon="icons.timeline" class="mx-auto mb-3 size-6 text-admin-text-faint" aria-hidden="true" />
        Для этой карточки пока нет ценовых наблюдений.
      </div>

      <div v-else class="min-w-[760px] divide-y divide-admin-border">
        <div
          v-for="(snapshot, index) in snapshots"
          :key="snapshot.id"
          class="grid grid-cols-[190px_180px_150px_170px_minmax(160px,1fr)] px-4 py-4 text-sm"
          data-testid="price-snapshot-row"
        >
          <div class="text-admin-text">{{ formatDateTime(snapshot.parsed_at) }}</div>
          <div class="font-medium text-admin-text">{{ formatSnapshotPrice(snapshot) }}</div>
          <div>
            <span
              class="rounded-full border px-2 py-1 text-xs"
              :class="
                snapshot.price === null
                  ? 'border-admin-danger-border bg-admin-danger-soft text-admin-danger'
                  : snapshotStatus(snapshot, index) === 'Цена изменилась'
                    ? 'border-admin-border-strong bg-admin-surface-muted text-admin-link'
                    : 'border-admin-border-strong bg-admin-surface-muted text-admin-text-muted'
              "
            >
              {{ snapshotStatus(snapshot, index) }}
            </span>
          </div>
          <div class="text-admin-text-muted">{{ formatDateTime(snapshot.source_updated_at) }}</div>
          <div class="text-admin-text-faint">#{{ snapshot.id }}</div>
        </div>
      </div>
    </div>

    <p v-if="productId" class="text-sm text-admin-text-faint">
      Изменений цены: {{ priceChanges }}.
    </p>
  </section>
</template>
