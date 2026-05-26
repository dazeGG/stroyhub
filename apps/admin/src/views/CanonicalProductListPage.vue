<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { useToast } from '@nuxt/ui/composables'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import {
  fetchCanonicalProducts,
  fetchCategories,
  type CanonicalProductListItem,
  type CategoryTreeItem,
} from '../lib/api'
import { icons } from '../lib/icons'
import { messageFromError, toastError } from '../lib/notifications'

interface CategoryOption {
  id: number
  label: string
}

type MatchStatusFilter = '' | 'active' | 'inactive'

const pageSize = 50
const route = useRoute()
const router = useRouter()
const toast = useToast()

const searchQuery = ref('')
const selectedCategoryId = ref('')
const selectedMatchStatus = ref<MatchStatusFilter>('active')
const offset = ref(0)
const totalProducts = ref(0)
const products = ref<CanonicalProductListItem[]>([])
const categories = ref<CategoryTreeItem[]>([])
const isLoadingProducts = ref(false)
const isLoadingFilters = ref(false)
const errorMessage = ref('')
const filterErrorMessage = ref('')

let productRequest: AbortController | null = null
let searchTimer: number | undefined
let syncingSearchQuery = false
let syncingCategoryQuery = false
let syncingStatusQuery = false
let syncingPageQuery = false

const categoryOptions = computed(() => flattenCategories(categories.value))

const acceptedOffersCount = computed(() => {
  return products.value.reduce((sum, product) => sum + product.match_counts.accepted, 0)
})

const candidateCount = computed(() => {
  return products.value.reduce((sum, product) => sum + product.match_counts.candidate, 0)
})

const currentPage = computed({
  get: () => Math.floor(offset.value / pageSize) + 1,
  set: (page: number) => {
    offset.value = Math.max(0, page - 1) * pageSize
  },
})

function flattenCategories(itemsToFlatten: CategoryTreeItem[], level = 0): CategoryOption[] {
  return itemsToFlatten.flatMap((category) => [
    { id: category.id, label: `${'— '.repeat(level)}${category.name}` },
    ...flattenCategories(category.children, level + 1),
  ])
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

function categoryLabel(product: CanonicalProductListItem): string {
  return product.category?.name || 'Без категории'
}

function statusLabel(status: string): string {
  if (status === 'active') {
    return 'Активен'
  }
  if (status === 'inactive') {
    return 'Отключен'
  }
  return status
}

function statusClass(status: string): string {
  if (status === 'active') {
    return 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'
  }
  if (status === 'inactive') {
    return 'border-neutral-700 bg-neutral-950 text-neutral-400'
  }
  return 'border-amber-400/30 bg-amber-400/10 text-amber-200'
}

function matchStatusFromRoute(value: unknown): MatchStatusFilter {
  if (value === 'inactive') {
    return 'inactive'
  }
  if (value === 'all') {
    return ''
  }
  return 'active'
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

function resetCatalogPageAndQuery(values: Record<string, string | undefined>): void {
  replaceCatalogQuery({ ...values, page: undefined })
  resetPaginationAndLoad()
}

function syncSearchFromRoute(): void {
  const routeSearch = route.query.q
  const nextSearch = typeof routeSearch === 'string' ? routeSearch : ''
  if (searchQuery.value === nextSearch) {
    return
  }

  syncingSearchQuery = true
  searchQuery.value = nextSearch
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

function syncStatusFromRoute(): void {
  const nextStatus = matchStatusFromRoute(route.query.status)
  if (selectedMatchStatus.value === nextStatus) {
    return
  }

  syncingStatusQuery = true
  selectedMatchStatus.value = nextStatus
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

async function loadFilters(): Promise<void> {
  isLoadingFilters.value = true
  filterErrorMessage.value = ''

  try {
    const response = await fetchCategories()
    categories.value = response.items
  } catch (error) {
    filterErrorMessage.value = messageFromError(error, 'Не удалось загрузить фильтры')
    toastError(toast, 'Не удалось загрузить фильтры', error, 'Не удалось загрузить фильтры')
  } finally {
    isLoadingFilters.value = false
  }
}

async function loadProducts(options: { preserveScroll?: boolean } = {}): Promise<void> {
  productRequest?.abort()
  const request = new AbortController()
  productRequest = request
  const scrollY = options.preserveScroll ? window.scrollY : null
  isLoadingProducts.value = true
  errorMessage.value = ''

  try {
    const response = await fetchCanonicalProducts(
      {
        q: searchQuery.value,
        categoryId: selectedCategoryId.value ? Number(selectedCategoryId.value) : undefined,
        matchStatus: selectedMatchStatus.value || undefined,
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

    errorMessage.value = messageFromError(error, 'Не удалось загрузить нормализованные товары')
    toastError(
      toast,
      'Не удалось загрузить нормализованные товары',
      error,
      'Не удалось загрузить нормализованные товары',
    )
    products.value = []
    totalProducts.value = 0
  } finally {
    if (productRequest === request) {
      isLoadingProducts.value = false
      if (scrollY !== null) {
        await nextTick()
        window.requestAnimationFrame(() => {
          window.scrollTo({ top: scrollY })
        })
      }
    }
  }
}

watch(selectedCategoryId, (categoryId) => {
  if (syncingCategoryQuery) {
    syncingCategoryQuery = false
    void loadProducts()
    return
  }

  resetCatalogPageAndQuery({ category: categoryId || undefined })
})

watch(selectedMatchStatus, (status) => {
  if (syncingStatusQuery) {
    syncingStatusQuery = false
    void loadProducts()
    return
  }

  resetCatalogPageAndQuery({
    status: status ? status : 'all',
  })
})

watch(() => route.query.q, syncSearchFromRoute)
watch(() => route.query.category, syncSelectedCategoryFromRoute)
watch(() => route.query.status, syncStatusFromRoute)
watch(() => route.query.page, syncPageFromRoute)

watch(offset, () => {
  if (syncingPageQuery) {
    syncingPageQuery = false
  } else {
    replaceCatalogQuery({
      page: currentPage.value > 1 ? String(currentPage.value) : undefined,
    })
  }

  void loadProducts({ preserveScroll: true })
})

watch(searchQuery, () => {
  window.clearTimeout(searchTimer)
  if (syncingSearchQuery) {
    syncingSearchQuery = false
    void loadProducts()
    return
  }

  searchTimer = window.setTimeout(() => {
    resetCatalogPageAndQuery({ q: searchQuery.value.trim() || undefined })
  }, 250)
})

onMounted(() => {
  syncSearchFromRoute()
  syncSelectedCategoryFromRoute()
  syncStatusFromRoute()
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
          <Icon :icon="icons.tags" class="size-4" aria-hidden="true" />
          Нормализованные товары
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-white">Canonical каталог</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
          Смотрим созданные canonical products, связанные офферы и очередь кандидатов.
        </p>
      </div>

      <div class="grid gap-3 sm:grid-cols-3 2xl:min-w-[640px]" data-testid="canonical-products-metrics">
        <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
          <p class="text-xs uppercase tracking-wide text-neutral-500">Товаров в списке</p>
          <p class="mt-1 text-xs text-neutral-600">по текущей странице</p>
          <p class="mt-2 text-2xl font-semibold text-white">{{ products.length }}</p>
        </div>
        <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
          <p class="text-xs uppercase tracking-wide text-neutral-500">Принятых офферов</p>
          <p class="mt-1 text-xs text-neutral-600">у этих товаров</p>
          <p class="mt-2 text-2xl font-semibold text-white">{{ acceptedOffersCount }}</p>
        </div>
        <div class="rounded-lg border border-amber-400/20 bg-amber-400/10 p-4">
          <p class="text-xs uppercase tracking-wide text-amber-200/80">Кандидатов на проверку</p>
          <p class="mt-1 text-xs text-amber-200/60">у этих товаров</p>
          <p class="mt-2 text-2xl font-semibold text-amber-100">{{ candidateCount }}</p>
        </div>
      </div>
    </div>

    <div
      class="grid gap-3 rounded-lg border border-neutral-800 bg-neutral-900/40 p-4 lg:grid-cols-[minmax(220px,1.3fr)_minmax(180px,1fr)_170px]"
      data-testid="canonical-products-filters"
    >
      <label class="relative">
        <Icon
          :icon="icons.search"
          class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-neutral-600"
          aria-hidden="true"
        />
        <input
          v-model="searchQuery"
          class="h-10 w-full rounded-md border border-neutral-800 bg-neutral-950 pl-9 pr-3 text-sm text-white outline-none transition placeholder:text-neutral-600 focus:border-amber-400"
          placeholder="Поиск по названию"
          type="search"
          aria-label="Поиск по названию нормализованного товара"
        >
      </label>

      <select
        v-model="selectedCategoryId"
        aria-label="Фильтр по категории"
        class="h-10 rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        :disabled="isLoadingFilters"
      >
        <option value="">Все категории</option>
        <option v-for="category in categoryOptions" :key="category.id" :value="String(category.id)">
          {{ category.label }}
        </option>
      </select>

      <select
        v-model="selectedMatchStatus"
        aria-label="Фильтр по статусу"
        class="h-10 rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition focus:border-amber-400"
      >
        <option value="active">Активные</option>
        <option value="inactive">Отключенные</option>
        <option value="">Все статусы</option>
      </select>
    </div>

    <div v-if="filterErrorMessage" class="rounded-lg border border-red-400/30 bg-red-400/10 p-4 text-sm text-red-100">
      {{ filterErrorMessage }}
    </div>

    <div class="overflow-x-auto rounded-lg border border-neutral-800 bg-neutral-900/40">
      <div
        class="grid min-w-[980px] grid-cols-[minmax(320px,2fr)_190px_140px_210px_150px] border-b border-neutral-800 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neutral-500"
      >
        <span>Товар</span>
        <span>Категория</span>
        <span>Статус</span>
        <span>Матчи</span>
        <span>Обновлен</span>
      </div>

      <div v-if="isLoadingProducts && products.length === 0" class="min-w-[980px] px-4 py-14 text-center text-sm text-neutral-500">
        <Icon :icon="icons.tags" class="mx-auto mb-3 size-6 text-neutral-600" aria-hidden="true" />
        Загружаем нормализованные товары...
      </div>

      <div
        v-else-if="errorMessage"
        class="min-w-[980px] px-4 py-14 text-center text-sm text-red-200"
      >
        <Icon :icon="icons.alertTriangle" class="mx-auto mb-3 size-6 text-red-300" aria-hidden="true" />
        Не удалось загрузить список: {{ errorMessage }}
      </div>

      <div
        v-else-if="products.length === 0"
        class="min-w-[980px] px-4 py-14 text-center text-sm text-neutral-500"
      >
        <Icon :icon="icons.search" class="mx-auto mb-3 size-6 text-neutral-600" aria-hidden="true" />
        По этим фильтрам нормализованных товаров нет.
      </div>

      <div
        v-else
        class="min-w-[980px] divide-y divide-neutral-800 transition-opacity"
        :class="isLoadingProducts ? 'opacity-60' : 'opacity-100'"
      >
        <div
          v-for="product in products"
          :key="product.id"
          class="grid grid-cols-[minmax(320px,2fr)_190px_140px_210px_150px] px-4 py-4 text-sm"
          data-testid="canonical-product-row"
        >
          <div class="min-w-0 pr-5">
            <RouterLink
              :to="{ name: 'canonical-product-detail', params: { canonicalProductId: product.id } }"
              class="truncate font-semibold text-white transition hover:text-amber-200"
              :title="product.title"
            >
              {{ product.title }}
            </RouterLink>
            <p class="mt-1 truncate text-xs text-neutral-500" :title="product.normalized_title">
              {{ product.normalized_title }}
            </p>
            <p v-if="product.brand || product.model || product.unit_raw" class="mt-1 truncate text-xs text-neutral-600">
              {{ [product.brand, product.model, product.unit_raw].filter(Boolean).join(' · ') }}
            </p>
          </div>

          <div class="min-w-0 pr-5">
            <p class="truncate text-neutral-200" :title="categoryLabel(product)">
              {{ categoryLabel(product) }}
            </p>
            <p v-if="product.category" class="mt-1 truncate text-xs text-neutral-600">
              {{ product.category.slug }}
            </p>
          </div>

          <div class="pr-5">
            <span class="inline-flex rounded-full border px-2 py-1 text-xs font-medium" :class="statusClass(product.match_status)">
              {{ statusLabel(product.match_status) }}
            </span>
          </div>

          <div class="grid grid-cols-3 gap-2 pr-5 text-center">
            <div>
              <p class="text-xs text-neutral-600">Офферы</p>
              <p class="mt-1 font-semibold text-white">{{ product.match_counts.accepted }}</p>
            </div>
            <div>
              <p class="text-xs text-neutral-600">Канд.</p>
              <p class="mt-1 font-semibold text-amber-100">{{ product.match_counts.candidate }}</p>
            </div>
            <div>
              <p class="text-xs text-neutral-600">Откл.</p>
              <p class="mt-1 font-semibold text-neutral-300">{{ product.match_counts.rejected }}</p>
            </div>
          </div>

          <div class="min-w-0 text-neutral-400">
            <p>{{ formatDateTime(product.updated_at) }}</p>
            <RouterLink
              class="mt-1 inline-flex items-center gap-1 text-xs font-medium text-amber-300 hover:text-amber-200"
              :to="{ name: 'canonical-product-detail', params: { canonicalProductId: product.id } }"
            >
              <Icon :icon="icons.pencil" class="size-3.5" aria-hidden="true" />
              Открыть
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
        :show-controls="false"
        show-edges
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
