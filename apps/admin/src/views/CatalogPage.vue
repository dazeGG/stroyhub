<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  fetchCategories,
  fetchProducts,
  fetchShops,
  type CategoryTreeItem,
  type ProductSearchItem,
  type ProductSort,
  type ShopListItem,
} from '../lib/api'
import { icons } from '../lib/icons'

const pageSize = 50
const route = useRoute()
const router = useRouter()
const searchQuery = ref('')
const selectedCategoryId = ref('')
const selectedShopId = ref('')
const sort = ref<ProductSort>('-last_seen_at')
const offset = ref(0)
const totalProducts = ref(0)
const products = ref<ProductSearchItem[]>([])
const categories = ref<CategoryTreeItem[]>([])
const shops = ref<ShopListItem[]>([])
const isLoadingProducts = ref(false)
const isLoadingFilters = ref(false)
const errorMessage = ref('')
const filterErrorMessage = ref('')

let productRequest: AbortController | null = null
let searchTimer: number | undefined
let syncingShopQuery = false
let syncingCategoryQuery = false
let syncingPageQuery = false

const categoryOptions = computed(() => {
  const options: { id: number; label: string }[] = []

  function walk(items: CategoryTreeItem[], depth: number): void {
    for (const item of items) {
      options.push({
        id: item.id,
        label: `${'  '.repeat(depth)}${item.name} (${item.product_count})`,
      })
      walk(item.children, depth + 1)
    }
  }

  walk(categories.value, 0)
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

const currentPage = computed({
  get: () => Math.floor(offset.value / pageSize) + 1,
  set: (page: number) => {
    offset.value = Math.max(0, page - 1) * pageSize
  },
})

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

function formatPrice(product: ProductSearchItem): string {
  if (!product.latest_price?.price) {
    return '-'
  }

  const amount = Number(product.latest_price.price)
  const value = Number.isFinite(amount)
    ? new Intl.NumberFormat('ru-RU', {
        maximumFractionDigits: 2,
        minimumFractionDigits: amount % 1 === 0 ? 0 : 2,
      }).format(amount)
    : product.latest_price.price
  const unit = product.latest_price.unit_raw ? ` / ${product.latest_price.unit_raw}` : ''

  return `${value} ${product.latest_price.currency}${unit}`
}

function categoryLabel(product: ProductSearchItem): string {
  if (!product.category_id) {
    return 'Не нормализовано'
  }

  return categoryNameById.value.get(product.category_id) || `ID ${product.category_id}`
}

function resetPagination(): void {
  offset.value = 0
}

function resetPaginationAndLoad(): void {
  if (offset.value === 0) {
    void loadProducts()
    return
  }

  resetPagination()
}

function replaceCatalogQuery(values: Record<string, string | undefined>): void {
  const nextQuery = { ...route.query }

  for (const [key, value] of Object.entries(values)) {
    if (value) {
      nextQuery[key] = value
    } else {
      delete nextQuery[key]
    }
  }

  void router.replace({ query: nextQuery })
}

function syncSelectedShopFromRoute(): void {
  const routeShop = route.query.shop
  const nextShopId = typeof routeShop === 'string' ? routeShop : ''
  if (selectedShopId.value === nextShopId) {
    return
  }

  syncingShopQuery = true
  selectedShopId.value = nextShopId
}

function syncSelectedCategoryFromRoute(): void {
  const routeCategory = route.query.category
  const nextCategoryId = typeof routeCategory === 'string' ? routeCategory : ''
  if (selectedCategoryId.value === nextCategoryId) {
    return
  }

  syncingCategoryQuery = true
  selectedCategoryId.value = nextCategoryId
}

function syncPageFromRoute(): void {
  const routePage = route.query.page
  const page = typeof routePage === 'string' ? Number.parseInt(routePage, 10) : 1
  const nextPage = Number.isFinite(page) && page > 1 ? page : 1
  const nextOffset = (nextPage - 1) * pageSize
  if (offset.value === nextOffset) {
    return
  }

  syncingPageQuery = true
  offset.value = nextOffset
}

function shopOptionLabel(shop: ShopListItem): string {
  return `${shop.name} · ${shop.source}`
}

async function loadFilters(): Promise<void> {
  isLoadingFilters.value = true
  filterErrorMessage.value = ''

  try {
    const [categoryResponse, shopResponse] = await Promise.all([fetchCategories(), fetchShops()])
    categories.value = categoryResponse.items
    shops.value = shopResponse.items
  } catch (error) {
    filterErrorMessage.value =
      error instanceof Error ? error.message : 'Не удалось загрузить фильтры каталога'
  } finally {
    isLoadingFilters.value = false
  }
}

async function loadProducts(): Promise<void> {
  productRequest?.abort()
  const request = new AbortController()
  productRequest = request
  isLoadingProducts.value = true
  errorMessage.value = ''

  try {
    const response = await fetchProducts(
      {
        q: searchQuery.value,
        categoryId: selectedCategoryId.value ? Number(selectedCategoryId.value) : undefined,
        shopId: selectedShopId.value ? Number(selectedShopId.value) : undefined,
        sort: sort.value,
        limit: pageSize,
        offset: offset.value,
      },
      request.signal,
    )
    products.value = response.items
    totalProducts.value = response.total
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }

    errorMessage.value = error instanceof Error ? error.message : 'Не удалось загрузить товары'
    products.value = []
    totalProducts.value = 0
  } finally {
    if (productRequest === request) {
      isLoadingProducts.value = false
    }
  }
}

watch([selectedCategoryId, selectedShopId, sort], () => {
  resetPaginationAndLoad()
})

watch(selectedShopId, (shopId) => {
  if (syncingShopQuery) {
    syncingShopQuery = false
    return
  }

  replaceCatalogQuery({ shop: shopId || undefined, page: undefined })
})

watch(selectedCategoryId, (categoryId) => {
  if (syncingCategoryQuery) {
    syncingCategoryQuery = false
    return
  }

  replaceCatalogQuery({ category: categoryId || undefined, page: undefined })
})

watch(() => route.query.shop, syncSelectedShopFromRoute)
watch(() => route.query.category, syncSelectedCategoryFromRoute)
watch(() => route.query.page, syncPageFromRoute)

watch(offset, () => {
  if (syncingPageQuery) {
    syncingPageQuery = false
  } else {
    replaceCatalogQuery({
      page: currentPage.value > 1 ? String(currentPage.value) : undefined,
    })
  }

  void loadProducts()
})

watch(searchQuery, () => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    resetPaginationAndLoad()
  }, 250)
})

onMounted(() => {
  syncSelectedShopFromRoute()
  syncSelectedCategoryFromRoute()
  syncPageFromRoute()
  void loadFilters()
  void loadProducts()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 2xl:flex-row 2xl:items-end 2xl:justify-between">
      <div>
        <p class="inline-flex items-center gap-2 text-sm font-medium text-amber-300">
          <Icon :icon="icons.package" class="size-4" aria-hidden="true" />
          Товары
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-white">Инспекция исходных карточек</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
          Ищем собранные карточки, сверяем категории и смотрим последние наблюдения по ценам.
        </p>
      </div>

      <div
        class="grid gap-3 lg:grid-cols-[minmax(180px,1.4fr)_minmax(180px,1fr)_minmax(160px,1fr)_170px] 2xl:min-w-[760px]"
        data-testid="catalog-filters"
      >
        <label class="relative">
          <Icon
            :icon="icons.search"
            class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-neutral-600"
            aria-hidden="true"
          />
          <input
            v-model="searchQuery"
            class="h-10 w-full rounded-md border border-neutral-800 bg-neutral-900 pl-9 pr-3 text-sm text-white outline-none transition placeholder:text-neutral-600 focus:border-amber-400"
            placeholder="Поиск по названию"
            type="search"
          />
        </label>
        <select
          v-model="selectedCategoryId"
          aria-label="Фильтр по категории"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
          :disabled="isLoadingFilters"
        >
          <option value="">Все категории</option>
          <option v-for="category in categoryOptions" :key="category.id" :value="String(category.id)">
            {{ category.label }}
          </option>
        </select>
        <select
          v-model="selectedShopId"
          aria-label="Фильтр по магазину"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
          :disabled="isLoadingFilters"
        >
          <option value="">Все магазины</option>
          <option v-for="shop in shops" :key="shop.id" :value="String(shop.id)">
            {{ shopOptionLabel(shop) }}
          </option>
        </select>
        <select
          v-model="sort"
          aria-label="Сортировка каталога"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        >
          <option value="-last_seen_at">Сначала свежие</option>
          <option value="last_seen_at">Сначала старые</option>
          <option value="latest_price">Цена по возрастанию</option>
          <option value="-latest_price">Цена по убыванию</option>
          <option value="title">Название A-Z</option>
          <option value="-title">Название Z-A</option>
          <option value="shop">Магазин A-Z</option>
          <option value="-shop">Магазин Z-A</option>
        </select>
      </div>
    </div>

    <div
      v-if="filterErrorMessage"
      class="rounded-lg border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-100"
    >
      Фильтры не загрузились: {{ filterErrorMessage }}
    </div>

    <div class="overflow-x-auto rounded-lg border border-neutral-800 bg-neutral-900/40">
      <div
        class="grid min-w-[920px] grid-cols-[minmax(280px,2fr)_170px_150px_150px_140px] border-b border-neutral-800 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neutral-500"
      >
        <span>Товар</span>
        <span>Магазин</span>
        <span>Категория</span>
        <span>Цена</span>
        <span>Последний раз</span>
      </div>

      <div v-if="isLoadingProducts" class="min-w-[920px] px-4 py-14 text-center text-sm text-neutral-500">
        <Icon :icon="icons.package" class="mx-auto mb-3 size-6 text-neutral-600" aria-hidden="true" />
        Загружаем каталог...
      </div>

      <div
        v-else-if="errorMessage"
        class="min-w-[920px] px-4 py-14 text-center text-sm text-red-200"
      >
        <Icon :icon="icons.alertTriangle" class="mx-auto mb-3 size-6 text-red-300" aria-hidden="true" />
        Не удалось загрузить каталог: {{ errorMessage }}
      </div>

      <div
        v-else-if="products.length === 0"
        class="min-w-[920px] px-4 py-14 text-center text-sm text-neutral-500"
      >
        <Icon :icon="icons.search" class="mx-auto mb-3 size-6 text-neutral-600" aria-hidden="true" />
        По этим фильтрам товаров не найдено.
      </div>

      <div v-else class="min-w-[920px] divide-y divide-neutral-800">
        <div
          v-for="product in products"
          :key="product.id"
          class="grid grid-cols-[minmax(280px,2fr)_170px_150px_150px_140px] gap-0 px-4 py-4 text-sm"
          data-testid="catalog-row"
        >
          <div class="min-w-0 pr-5">
            <p class="truncate font-medium text-white" :title="product.title">{{ product.title }}</p>
            <p class="mt-1 truncate text-xs text-neutral-500" :title="product.normalized_title">
              {{ product.source }} · {{ product.source_product_id || 'без source id' }}
            </p>
          </div>
          <div class="min-w-0 pr-5">
            <p class="truncate text-neutral-200" :title="product.shop.name">{{ product.shop.name }}</p>
            <p class="mt-1 truncate text-xs text-neutral-500" :title="product.shop.source_id">
              {{ product.shop.source_id }}
            </p>
          </div>
          <div class="min-w-0 pr-5">
            <p class="truncate text-neutral-200" :title="categoryLabel(product)">
              {{ categoryLabel(product) }}
            </p>
            <p class="mt-1 truncate text-xs text-neutral-500" :title="product.category_raw || 'Без исходной категории'">
              {{ product.category_raw || 'Без исходной категории' }}
            </p>
          </div>
          <div class="pr-5 text-neutral-200">{{ formatPrice(product) }}</div>
          <div class="min-w-0 text-neutral-400">
            <p>{{ formatDateTime(product.last_seen_at) }}</p>
            <RouterLink
              class="mt-1 inline-flex items-center gap-1 text-xs font-medium text-amber-300 hover:text-amber-200"
              data-testid="catalog-price-link"
              :to="{ name: 'product-detail', params: { productId: product.id } }"
            >
              <Icon :icon="icons.history" class="size-3.5" aria-hidden="true" />
              История цен
            </RouterLink>
          </div>
        </div>
      </div>
    </div>

    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <p class="text-sm text-neutral-500">
        Страница {{ currentPage }} · показано {{ products.length }} из {{ totalProducts }}
      </p>
      <UPagination
        v-model:page="currentPage"
        :disabled="isLoadingProducts"
        :items-per-page="pageSize"
        :sibling-count="1"
        :total="totalProducts"
        active-color="neutral"
        active-variant="solid"
        color="neutral"
        size="sm"
        variant="outline"
      />
    </div>
  </section>
</template>
