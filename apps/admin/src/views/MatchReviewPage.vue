<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { computed, onMounted, ref, watch } from 'vue'

import {
  fetchMatchCandidates,
  fetchShops,
  type MatchCandidatePair,
  type MatchCandidateProduct,
  type ShopListItem,
} from '../lib/api'
import { icons } from '../lib/icons'

const selectedSource = ref('')
const selectedShopId = ref('')
const minConfidence = ref('0.75')
const shops = ref<ShopListItem[]>([])
const productsConsidered = ref(0)
const candidates = ref<MatchCandidatePair[]>([])
const isLoading = ref(false)
const errorMessage = ref('')

let candidateRequest: AbortController | null = null

const sourceOptions = computed(() => {
  return Array.from(new Set(shops.value.map((shop) => shop.source))).sort()
})

const filteredShopOptions = computed(() => {
  if (!selectedSource.value) {
    return shops.value
  }

  return shops.value.filter((shop) => shop.source === selectedSource.value)
})

function confidencePercent(value: number): string {
  return `${Math.round(value * 100)}%`
}

function reasonTokens(tokens: string[]): string {
  return tokens.length ? tokens.join(', ') : '-'
}

function categoryLabel(product: MatchCandidateProduct): string {
  if (product.category_raw) {
    return product.category_raw
  }
  if (product.category_id) {
    return `category #${product.category_id}`
  }

  return 'Без категории'
}

function productExport(product: MatchCandidateProduct): string {
  return `#${product.id} · ${product.shop_name} · ${product.title}`
}

async function loadCandidates(): Promise<void> {
  candidateRequest?.abort()
  const request = new AbortController()
  candidateRequest = request
  isLoading.value = true
  errorMessage.value = ''

  try {
    const [shopResponse, candidateResponse] = await Promise.all([
      fetchShops({}, request.signal),
      fetchMatchCandidates(
        {
          source: selectedSource.value,
          shopId: selectedShopId.value ? Number(selectedShopId.value) : undefined,
          minConfidence: Number(minConfidence.value),
          limit: 50,
        },
        request.signal,
      ),
    ])
    shops.value = shopResponse.items
    productsConsidered.value = candidateResponse.products_considered
    candidates.value = candidateResponse.candidates
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }

    errorMessage.value =
      error instanceof Error ? error.message : 'Не удалось загрузить кандидатов матчинга'
    productsConsidered.value = 0
    candidates.value = []
  } finally {
    if (candidateRequest === request) {
      isLoading.value = false
    }
  }
}

watch(selectedSource, () => {
  if (selectedSource.value && selectedShopId.value) {
    const selectedShop = shops.value.find((shop) => String(shop.id) === selectedShopId.value)
    if (selectedShop && selectedShop.source !== selectedSource.value) {
      selectedShopId.value = ''
      return
    }
  }

  void loadCandidates()
})

watch([selectedShopId, minConfidence], () => {
  void loadCandidates()
})

onMounted(() => {
  void loadCandidates()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 2xl:flex-row 2xl:items-end 2xl:justify-between">
      <div>
        <p class="inline-flex items-center gap-2 text-sm font-medium text-amber-300">
          <Icon :icon="icons.gitCompare" class="size-4" aria-hidden="true" />
          Матчинг товаров
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-white">Кандидаты на ревью</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
          Read-only сравнение возможных дублей: confidence, reasons и пары карточек без accept/reject действий.
        </p>
      </div>

      <div
        class="grid gap-3 lg:grid-cols-[minmax(150px,1fr)_minmax(220px,1.5fr)_150px] 2xl:min-w-[720px]"
        data-testid="match-review-filters"
      >
        <select
          v-model="selectedSource"
          aria-label="Фильтр кандидатов матчинга по источнику"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        >
          <option value="">Все источники</option>
          <option v-for="source in sourceOptions" :key="source" :value="source">
            {{ source }}
          </option>
        </select>
        <select
          v-model="selectedShopId"
          aria-label="Фильтр кандидатов матчинга по магазину"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        >
          <option value="">Все магазины</option>
          <option v-for="shop in filteredShopOptions" :key="shop.id" :value="String(shop.id)">
            {{ shop.name }} · {{ shop.source }}
          </option>
        </select>
        <select
          v-model="minConfidence"
          aria-label="Минимальная уверенность кандидатов"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        >
          <option value="0.75">75%+</option>
          <option value="0.85">85%+</option>
          <option value="0.95">95%+</option>
        </select>
      </div>
    </div>

    <div
      v-if="errorMessage"
      class="rounded-lg border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-100"
    >
      Не удалось загрузить кандидатов матчинга: {{ errorMessage }}
    </div>

    <div class="grid gap-4 md:grid-cols-3">
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="inline-flex items-center gap-2 text-sm text-neutral-500">
          <Icon :icon="icons.shoppingBag" class="size-4" aria-hidden="true" />
          Товаров проверено
        </p>
        <p class="mt-3 text-3xl font-semibold text-white">{{ productsConsidered }}</p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="inline-flex items-center gap-2 text-sm text-neutral-500">
          <Icon :icon="icons.link" class="size-4" aria-hidden="true" />
          Кандидатов
        </p>
        <p class="mt-3 text-3xl font-semibold text-white">{{ candidates.length }}</p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="inline-flex items-center gap-2 text-sm text-neutral-500">
          <Icon :icon="icons.shieldLock" class="size-4" aria-hidden="true" />
          Режим
        </p>
        <p class="mt-3 text-lg font-semibold text-white">Read-only</p>
      </div>
    </div>

    <div v-if="isLoading" class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-8 text-center text-sm text-neutral-500">
      <Icon :icon="icons.gitCompare" class="mx-auto mb-3 size-6 text-neutral-600" aria-hidden="true" />
      Загружаем кандидатов...
    </div>

    <div
      v-else-if="candidates.length === 0"
      class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-8 text-center text-sm text-neutral-500"
    >
      <Icon :icon="icons.search" class="mx-auto mb-3 size-6 text-neutral-600" aria-hidden="true" />
      Кандидатов по этим фильтрам нет.
    </div>

    <div v-else class="space-y-4">
      <article
        v-for="candidate in candidates"
        :key="`${candidate.left.id}:${candidate.right.id}`"
        class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4"
        data-testid="match-candidate-row"
      >
        <div class="flex flex-col gap-3 border-b border-neutral-800 pb-4 md:flex-row md:items-center md:justify-between">
          <div>
            <p class="inline-flex items-center gap-2 text-sm font-semibold text-white">
              <Icon :icon="icons.link" class="size-4 text-amber-300" aria-hidden="true" />
              {{ confidencePercent(candidate.confidence) }} · {{ candidate.reason.method }}
            </p>
            <p class="mt-1 text-xs text-neutral-500">
              token similarity {{ confidencePercent(candidate.reason.token_similarity) }} · same category
              {{ candidate.reason.same_category === null ? '-' : candidate.reason.same_category ? 'yes' : 'no' }}
            </p>
          </div>
          <span class="inline-flex w-fit items-center gap-1 rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-1 text-xs text-amber-200">
            <Icon :icon="icons.shieldLock" class="size-3.5" aria-hidden="true" />
            actions deferred
          </span>
        </div>

        <div class="mt-4 grid gap-4 xl:grid-cols-2">
          <div
            v-for="product in [candidate.left, candidate.right]"
            :key="product.id"
            class="rounded-lg border border-neutral-800 bg-neutral-950/40 p-4"
          >
            <p class="text-xs font-semibold uppercase tracking-wide text-neutral-500">
              {{ product.source }} · {{ product.shop_name }}
            </p>
            <h3 class="mt-2 text-base font-semibold text-white">{{ product.title }}</h3>
            <dl class="mt-4 grid gap-3 text-sm text-neutral-400 sm:grid-cols-2">
              <div>
                <dt class="text-xs uppercase tracking-wide text-neutral-600">Product ID</dt>
                <dd class="mt-1 text-neutral-200">#{{ product.id }}</dd>
              </div>
              <div>
                <dt class="text-xs uppercase tracking-wide text-neutral-600">Shop source ID</dt>
                <dd class="mt-1 text-neutral-200">{{ product.shop_source_id }}</dd>
              </div>
              <div>
                <dt class="text-xs uppercase tracking-wide text-neutral-600">Category</dt>
                <dd class="mt-1 text-neutral-200">{{ categoryLabel(product) }}</dd>
              </div>
              <div>
                <dt class="text-xs uppercase tracking-wide text-neutral-600">Normalized</dt>
                <dd class="mt-1 truncate text-neutral-200" :title="product.normalized_title">
                  {{ product.normalized_title }}
                </dd>
              </div>
            </dl>
          </div>
        </div>

        <div class="mt-4 grid gap-3 text-sm lg:grid-cols-3">
          <div class="rounded-md bg-neutral-950/40 p-3">
            <p class="text-xs uppercase tracking-wide text-neutral-600">Overlap</p>
            <p class="mt-2 text-neutral-300">{{ reasonTokens(candidate.reason.token_overlap) }}</p>
          </div>
          <div class="rounded-md bg-neutral-950/40 p-3">
            <p class="text-xs uppercase tracking-wide text-neutral-600">Left only</p>
            <p class="mt-2 text-neutral-300">{{ reasonTokens(candidate.reason.left_only_tokens) }}</p>
          </div>
          <div class="rounded-md bg-neutral-950/40 p-3">
            <p class="text-xs uppercase tracking-wide text-neutral-600">Right only</p>
            <p class="mt-2 text-neutral-300">{{ reasonTokens(candidate.reason.right_only_tokens) }}</p>
          </div>
        </div>

        <p class="mt-3 font-mono text-xs text-neutral-500">
          {{ productExport(candidate.left) }} ⇄ {{ productExport(candidate.right) }}
        </p>
      </article>
    </div>
  </section>
</template>
