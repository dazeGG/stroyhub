<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { useToast } from '@nuxt/ui/composables'
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import {
  fetchCanonicalProduct,
  fetchCategories,
  updateCanonicalProduct,
  type CanonicalLinkedSourceProduct,
  type CanonicalProductDetail,
  type CategoryTreeItem,
} from '../lib/api'
import { icons } from '../lib/icons'
import { messageFromError, toastError, toastSuccess } from '../lib/notifications'

interface CategoryOption {
  id: number
  label: string
}

const route = useRoute()
const toast = useToast()

const product = ref<CanonicalProductDetail | null>(null)
const categories = ref<CategoryTreeItem[]>([])
const isLoading = ref(false)
const isSaving = ref(false)
const errorMessage = ref('')
const attributesText = ref('{}')
const form = ref({
  title: '',
  normalized_title: '',
  category_id: '',
  brand: '',
  model: '',
  unit_raw: '',
  match_status: 'active',
})

let productRequest: AbortController | null = null

const canonicalProductId = computed(() => {
  const rawValue = Array.isArray(route.params.canonicalProductId)
    ? route.params.canonicalProductId[0]
    : route.params.canonicalProductId
  const parsed = Number(rawValue)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
})

const categoryOptions = computed(() => flattenCategories(categories.value))

const acceptedOffersCount = computed(() => {
  return product.value?.accepted_offer_groups.reduce((sum, group) => sum + group.items.length, 0) ?? 0
})

function hydrateForm(nextProduct: CanonicalProductDetail): void {
  form.value = {
    title: nextProduct.title,
    normalized_title: nextProduct.normalized_title,
    category_id: nextProduct.category_id ? String(nextProduct.category_id) : '',
    brand: nextProduct.brand ?? '',
    model: nextProduct.model ?? '',
    unit_raw: nextProduct.unit_raw ?? '',
    match_status: nextProduct.match_status,
  }
  attributesText.value = JSON.stringify(nextProduct.attributes ?? {}, null, 2)
}

function flattenCategories(itemsToFlatten: CategoryTreeItem[], level = 0): CategoryOption[] {
  return itemsToFlatten.flatMap((category) => [
    { id: category.id, label: `${'— '.repeat(level)}${category.name}` },
    ...flattenCategories(category.children, level + 1),
  ])
}

function formatMoney(
  price: string | null,
  currency: string,
  unitRaw: string | null,
  priceKind = 'exact',
): string {
  if (price === null) {
    return 'Цена отсутствует'
  }

  const amount = Number(price)
  const value = Number.isFinite(amount)
    ? new Intl.NumberFormat('ru-RU', {
        maximumFractionDigits: 2,
        minimumFractionDigits: amount % 1 === 0 ? 0 : 2,
      }).format(amount)
    : price
  const prefix = priceKind === 'from' || priceKind === 'range' ? 'от ' : ''
  return `${prefix}${value} ${currency}${unitRaw ? ` / ${unitRaw}` : ''}`
}

function formatLatestPrice(item: CanonicalLinkedSourceProduct): string {
  if (!item.latest_price) {
    return 'Нет наблюдений цены'
  }

  return formatMoney(
    item.latest_price.price,
    item.latest_price.currency,
    item.latest_price.unit_raw,
    item.latest_price.price_kind,
  )
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

function confidencePercent(value: string): string {
  return `${Math.round(Number(value) * 100)}%`
}

async function loadProduct(nextProductId: number): Promise<void> {
  productRequest?.abort()
  const request = new AbortController()
  productRequest = request
  isLoading.value = true
  errorMessage.value = ''

  try {
    const [productResponse, categoryResponse] = await Promise.all([
      fetchCanonicalProduct(nextProductId, request.signal),
      fetchCategories(request.signal),
    ])
    product.value = productResponse
    categories.value = categoryResponse.items
    hydrateForm(productResponse)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }

    errorMessage.value = messageFromError(error, 'Не удалось загрузить нормализованный товар')
    toastError(
      toast,
      'Не удалось загрузить нормализованный товар',
      error,
      'Не удалось загрузить нормализованный товар',
    )
    product.value = null
  } finally {
    if (productRequest === request) {
      isLoading.value = false
    }
  }
}

async function saveProduct(): Promise<void> {
  if (!canonicalProductId.value) {
    return
  }

  let attributes: Record<string, unknown> | null
  try {
    const parsed = attributesText.value.trim() ? JSON.parse(attributesText.value) : null
    attributes = parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null
  } catch {
    errorMessage.value = 'Attributes должны быть валидным JSON-объектом'
    return
  }

  isSaving.value = true
  errorMessage.value = ''

  try {
    const updated = await updateCanonicalProduct(canonicalProductId.value, {
      title: form.value.title,
      normalized_title: form.value.normalized_title,
      category_id: form.value.category_id ? Number(form.value.category_id) : null,
      brand: form.value.brand || null,
      model: form.value.model || null,
      unit_raw: form.value.unit_raw || null,
      attributes,
      match_status: form.value.match_status,
    })
    product.value = updated
    hydrateForm(updated)
    toastSuccess(toast, 'Нормализованный товар сохранен', updated.title)
  } catch (error) {
    errorMessage.value = messageFromError(error, 'Не удалось сохранить нормализованный товар')
    toastError(
      toast,
      'Не удалось сохранить нормализованный товар',
      error,
      'Не удалось сохранить нормализованный товар',
    )
  } finally {
    isSaving.value = false
  }
}

watch(canonicalProductId, (nextProductId) => {
  if (nextProductId) {
    void loadProduct(nextProductId)
  }
})

onMounted(() => {
  if (canonicalProductId.value) {
    void loadProduct(canonicalProductId.value)
  }
})
</script>

<template>
  <section class="space-y-6" data-testid="canonical-product-detail">
    <div class="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
      <div>
        <RouterLink
          to="/canonical-products"
          class="inline-flex items-center gap-2 text-sm font-medium text-admin-text-muted transition hover:text-admin-text"
        >
          <Icon :icon="icons.arrowLeft" class="size-4" aria-hidden="true" />
          К списку нормализованных
        </RouterLink>
        <p class="mt-5 flex items-center gap-2 text-sm font-medium text-admin-link">
          <Icon :icon="icons.package" class="size-4" aria-hidden="true" />
          Нормализованный товар
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-admin-text">
          {{ product?.title || 'Загрузка товара' }}
        </h2>
      </div>

      <div class="grid gap-3 sm:grid-cols-3 xl:min-w-[560px]">
        <div class="rounded-lg border border-admin-border bg-admin-surface p-4">
          <p class="text-xs uppercase tracking-wide text-admin-text-faint">Офферов</p>
          <p class="mt-2 text-2xl font-semibold text-admin-text">{{ acceptedOffersCount }}</p>
        </div>
        <div class="rounded-lg border border-admin-border bg-admin-surface p-4">
          <p class="text-xs uppercase tracking-wide text-admin-text-faint">Кандидатов</p>
          <p class="mt-2 text-2xl font-semibold text-admin-text">{{ product?.match_counts.candidate ?? 0 }}</p>
        </div>
        <div class="rounded-lg border border-admin-border bg-admin-surface p-4">
          <p class="text-xs uppercase tracking-wide text-admin-text-faint">Отклонено</p>
          <p class="mt-2 text-2xl font-semibold text-admin-text">{{ product?.match_counts.rejected ?? 0 }}</p>
        </div>
      </div>
    </div>

    <div v-if="errorMessage" class="rounded-lg border border-admin-danger-border bg-admin-danger-soft p-4 text-sm text-admin-danger">
      {{ errorMessage }}
    </div>

    <div v-if="isLoading" class="rounded-lg border border-admin-border bg-admin-surface p-8 text-center text-sm text-admin-text-faint">
      <Icon :icon="icons.package" class="mx-auto mb-3 size-6 text-admin-text-faint" aria-hidden="true" />
      Загружаем нормализованный товар...
    </div>

    <template v-else-if="product">
      <div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <form class="rounded-lg border border-admin-border bg-admin-surface p-5" @submit.prevent="saveProduct">
          <div class="grid gap-4 md:grid-cols-2">
            <label class="block md:col-span-2">
              <span class="text-xs uppercase tracking-wide text-admin-text-faint">Название</span>
              <input
                v-model="form.title"
                class="mt-2 h-10 w-full rounded-md border border-admin-border bg-admin-surface px-3 text-sm text-admin-text outline-none transition focus:border-admin-focus"
                required
              >
            </label>
            <label class="block md:col-span-2">
              <span class="text-xs uppercase tracking-wide text-admin-text-faint">Нормализованное название</span>
              <input
                v-model="form.normalized_title"
                class="mt-2 h-10 w-full rounded-md border border-admin-border bg-admin-surface px-3 text-sm text-admin-text outline-none transition focus:border-admin-focus"
                required
              >
            </label>
            <label class="block">
              <span class="text-xs uppercase tracking-wide text-admin-text-faint">Категория</span>
              <select
                v-model="form.category_id"
                class="mt-2 h-10 w-full rounded-md border border-admin-border bg-admin-surface px-3 text-sm text-admin-text outline-none transition focus:border-admin-focus"
              >
                <option value="">Без категории</option>
                <option v-for="category in categoryOptions" :key="category.id" :value="String(category.id)">
                  {{ category.label }}
                </option>
              </select>
            </label>
            <label class="block">
              <span class="text-xs uppercase tracking-wide text-admin-text-faint">Статус</span>
              <select
                v-model="form.match_status"
                class="mt-2 h-10 w-full rounded-md border border-admin-border bg-admin-surface px-3 text-sm text-admin-text outline-none transition focus:border-admin-focus"
              >
                <option value="active">active</option>
                <option value="inactive">inactive</option>
              </select>
            </label>
            <label class="block">
              <span class="text-xs uppercase tracking-wide text-admin-text-faint">Бренд</span>
              <input
                v-model="form.brand"
                class="mt-2 h-10 w-full rounded-md border border-admin-border bg-admin-surface px-3 text-sm text-admin-text outline-none transition focus:border-admin-focus"
              >
            </label>
            <label class="block">
              <span class="text-xs uppercase tracking-wide text-admin-text-faint">Модель</span>
              <input
                v-model="form.model"
                class="mt-2 h-10 w-full rounded-md border border-admin-border bg-admin-surface px-3 text-sm text-admin-text outline-none transition focus:border-admin-focus"
              >
            </label>
            <label class="block md:col-span-2">
              <span class="text-xs uppercase tracking-wide text-admin-text-faint">Единица</span>
              <input
                v-model="form.unit_raw"
                class="mt-2 h-10 w-full rounded-md border border-admin-border bg-admin-surface px-3 text-sm text-admin-text outline-none transition focus:border-admin-focus"
              >
            </label>
            <label class="block md:col-span-2">
              <span class="text-xs uppercase tracking-wide text-admin-text-faint">Атрибуты JSON</span>
              <textarea
                v-model="attributesText"
                class="mt-2 min-h-40 w-full rounded-md border border-admin-border bg-admin-surface px-3 py-2 font-mono text-sm text-admin-text outline-none transition focus:border-admin-focus"
              />
            </label>
          </div>

          <button
            type="submit"
            class="mt-5 inline-flex items-center justify-center gap-2 rounded-md bg-admin-primary px-4 py-2 text-sm font-semibold text-admin-primary-text transition hover:bg-admin-primary-hover disabled:cursor-wait disabled:opacity-60"
            :disabled="isSaving"
          >
            <Icon :icon="icons.check" class="size-4" aria-hidden="true" />
            {{ isSaving ? 'Сохраняем...' : 'Сохранить' }}
          </button>
        </form>

        <aside class="space-y-4">
          <section class="rounded-lg border border-admin-border bg-admin-surface p-5">
            <h3 class="text-sm font-semibold text-admin-text">Принятые офферы</h3>
            <div v-if="product.accepted_offer_groups.length" class="mt-4 space-y-4">
              <div v-for="group in product.accepted_offer_groups" :key="`${group.source}:${group.shop_id}`">
                <p class="text-sm font-semibold text-admin-link">{{ group.shop_name }}</p>
                <p class="text-xs text-admin-text-faint">{{ group.source }} · {{ group.shop_source_id }}</p>
                <div class="mt-3 space-y-3">
                  <div v-for="item in group.items" :key="item.match_id" class="border-t border-admin-border pt-3">
                    <RouterLink :to="`/products/${item.id}`" class="text-sm font-semibold text-admin-text transition hover:text-admin-link-hover">
                      {{ item.title }}
                    </RouterLink>
                    <p class="mt-1 text-sm text-admin-text-muted">{{ formatLatestPrice(item) }}</p>
                    <p class="mt-1 text-xs text-admin-text-faint">{{ item.category_raw || 'Без raw категории' }} · {{ formatDateTime(item.last_seen_at) }}</p>
                  </div>
                </div>
              </div>
            </div>
            <p v-else class="mt-4 text-sm text-admin-text-faint">Принятых source-карточек пока нет.</p>
          </section>

          <section class="rounded-lg border border-admin-border bg-admin-surface p-5">
            <h3 class="text-sm font-semibold text-admin-text">Кандидаты и отклоненные</h3>
            <div class="mt-4 space-y-4">
              <div>
                <p class="text-xs uppercase tracking-wide text-admin-text-faint">Кандидаты</p>
                <div v-if="product.candidate_source_products.length" class="mt-2 space-y-2">
                  <RouterLink
                    v-for="item in product.candidate_source_products"
                    :key="item.match_id"
                    :to="`/products/${item.id}`"
                    class="block rounded-md border border-admin-border px-3 py-2 text-sm text-admin-text transition hover:border-admin-primary"
                  >
                    {{ item.title }} · {{ confidencePercent(item.confidence) }}
                  </RouterLink>
                </div>
                <p v-else class="mt-2 text-sm text-admin-text-faint">Кандидатов нет.</p>
              </div>
              <div>
                <p class="text-xs uppercase tracking-wide text-admin-text-faint">Отклоненные</p>
                <div v-if="product.rejected_source_products.length" class="mt-2 space-y-2">
                  <RouterLink
                    v-for="item in product.rejected_source_products"
                    :key="item.match_id"
                    :to="`/products/${item.id}`"
                    class="block rounded-md border border-admin-border px-3 py-2 text-sm text-admin-text transition hover:border-admin-border-strong"
                  >
                    {{ item.title }} · {{ confidencePercent(item.confidence) }}
                  </RouterLink>
                </div>
                <p v-else class="mt-2 text-sm text-admin-text-faint">Отклоненных матчей нет.</p>
              </div>
            </div>
          </section>
        </aside>
      </div>
    </template>
  </section>
</template>
