<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { computed, onMounted, reactive, ref, watch } from 'vue'

import {
  createShopIdentity,
  fetchShopIdentities,
  fetchShops,
  linkShopSource,
  unlinkShopSource,
  updateShopIdentity,
  type IdentityStatus,
  type ShopIdentity,
  type ShopIdentitySavePayload,
  type ShopListItem,
  type SourceType,
} from '../lib/api'
import { icons } from '../lib/icons'

const statusOptions: Array<{ value: IdentityStatus; label: string }> = [
  { value: 'active', label: 'Активен' },
  { value: 'hold', label: 'Hold' },
  { value: 'disabled', label: 'Отключен' },
  { value: 'out_of_scope', label: 'Вне MVP' },
]

const sourceTypeOptions: Array<{ value: SourceType; label: string }> = [
  { value: '2gis', label: '2GIS' },
  { value: 'official_api', label: 'Официальный API' },
  { value: 'official_html', label: 'Официальный HTML' },
]

const identities = ref<ShopIdentity[]>([])
const shops = ref<ShopListItem[]>([])
const allShops = ref<ShopListItem[]>([])
const selectedSource = ref('')
const selectedStatus = ref('')
const selectedSourceType = ref<SourceType | ''>('')
const selectedRelationship = ref<'linked' | 'unlinked' | ''>('')
const selectedIdentityId = ref<number | ''>('')
const isLoading = ref(false)
const errorMessage = ref('')
const saveMessage = ref('')
const savingIdentityId = ref<number | null>(null)
const linkingShopId = ref<number | null>(null)
const linkTargets = reactive<Record<number, number | ''>>({})
const editForms = reactive<Record<number, ShopIdentitySavePayload>>({})
const createForm = reactive<Required<Pick<ShopIdentitySavePayload, 'display_name'>> & ShopIdentitySavePayload>({
  display_name: '',
  address: '',
  website_url: '',
  preferred_source: '',
  status: 'active',
  notes: '',
  locked_fields: null,
})

let shopsRequest: AbortController | null = null

const sourceOptions = computed(() => {
  return Array.from(new Set(allShops.value.map((shop) => shop.source))).sort()
})

const scrapeStatusOptions = computed(() => {
  return Array.from(new Set(allShops.value.map((shop) => shop.scrape_status))).sort()
})

const groupedSourceCount = computed(() => {
  return allShops.value.filter((shop) => shop.shop_identity_id !== null).length
})

const ungroupedSourceCount = computed(() => {
  return allShops.value.length - groupedSourceCount.value
})

const failingSourceCount = computed(() => {
  return allShops.value.filter((shop) => ['failed', 'partial'].includes(shop.scrape_status)).length
})

const heldIdentityCount = computed(() => {
  return identities.value.filter((identity) => identity.status === 'hold' || identity.status === 'disabled').length
})

const linkedShopsByIdentity = computed(() => {
  const grouped = new Map<number, ShopListItem[]>()
  for (const shop of allShops.value) {
    if (shop.shop_identity_id === null) {
      continue
    }
    const existing = grouped.get(shop.shop_identity_id) || []
    existing.push(shop)
    grouped.set(shop.shop_identity_id, existing)
  }

  return grouped
})

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    active: 'Активен',
    disabled: 'Отключен',
    failed: 'Ошибка',
    hold: 'Hold',
    new: 'Новый',
    out_of_scope: 'Вне MVP',
    partial: 'Частично',
    running: 'В процессе',
    success: 'Успешно',
  }

  return labels[status] || status
}

function sourceTypeLabel(sourceType: string): string {
  return sourceTypeOptions.find((option) => option.value === sourceType)?.label || sourceType
}

function statusClass(status: string): string {
  if (status === 'failed') {
    return 'border-red-400/30 bg-red-400/10 text-red-200'
  }
  if (status === 'partial' || status === 'hold') {
    return 'border-amber-400/30 bg-amber-400/10 text-amber-200'
  }
  if (status === 'success' || status === 'active') {
    return 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'
  }
  if (status === 'disabled' || status === 'out_of_scope') {
    return 'border-neutral-700 bg-neutral-900 text-neutral-500'
  }

  return 'border-neutral-700 bg-neutral-900 text-neutral-300'
}

function sourceTypeClass(sourceType: string): string {
  if (sourceType === 'official_api') {
    return 'border-sky-400/30 bg-sky-400/10 text-sky-200'
  }
  if (sourceType === 'official_html') {
    return 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'
  }

  return 'border-neutral-700 bg-neutral-900 text-neutral-300'
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

function identityForm(identity: ShopIdentity): ShopIdentitySavePayload {
  if (!editForms[identity.id]) {
    editForms[identity.id] = {
      display_name: identity.display_name,
      address: identity.address || '',
      website_url: identity.website_url || '',
      preferred_source: identity.preferred_source || '',
      status: identity.status,
      notes: identity.notes || '',
      locked_fields: identity.locked_fields,
    }
  }

  return editForms[identity.id]
}

function normalizePayload(payload: ShopIdentitySavePayload): ShopIdentitySavePayload {
  return {
    display_name: payload.display_name?.trim(),
    address: payload.address?.trim() || null,
    website_url: payload.website_url?.trim() || null,
    preferred_source: payload.preferred_source?.trim() || null,
    status: payload.status,
    notes: payload.notes?.trim() || null,
    locked_fields: payload.locked_fields || null,
  }
}

async function loadShopManagement(): Promise<void> {
  shopsRequest?.abort()
  const request = new AbortController()
  shopsRequest = request
  isLoading.value = true
  errorMessage.value = ''
  saveMessage.value = ''

  try {
    const [identityResponse, allShopResponse, shopResponse] = await Promise.all([
      fetchShopIdentities({}, request.signal),
      fetchShops({}, request.signal),
      fetchShops(
        {
          source: selectedSource.value,
          status: selectedStatus.value,
          sourceType: selectedSourceType.value,
          identityId: selectedIdentityId.value || undefined,
          identity: selectedRelationship.value,
        },
        request.signal,
      ),
    ])
    identities.value = identityResponse.items
    allShops.value = allShopResponse.items
    shops.value = shopResponse.items
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }

    errorMessage.value = error instanceof Error ? error.message : 'Не удалось загрузить магазины'
    identities.value = []
    allShops.value = []
    shops.value = []
  } finally {
    if (shopsRequest === request) {
      isLoading.value = false
    }
  }
}

async function saveIdentity(identity: ShopIdentity): Promise<void> {
  savingIdentityId.value = identity.id
  errorMessage.value = ''
  saveMessage.value = ''

  try {
    const updated = await updateShopIdentity(identity.id, normalizePayload(identityForm(identity)))
    identities.value = identities.value.map((item) => (item.id === updated.id ? updated : item))
    editForms[updated.id] = normalizePayload(updated)
    saveMessage.value = 'Метаданные магазина сохранены'
    await loadShopManagement()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Не удалось сохранить магазин'
  } finally {
    savingIdentityId.value = null
  }
}

async function createIdentity(): Promise<void> {
  if (!createForm.display_name.trim()) {
    errorMessage.value = 'Укажите название магазина'
    return
  }

  savingIdentityId.value = 0
  errorMessage.value = ''
  saveMessage.value = ''

  try {
    const created = await createShopIdentity(normalizePayload(createForm))
    identities.value = [...identities.value, created].sort((left, right) =>
      left.display_name.localeCompare(right.display_name, 'ru'),
    )
    createForm.display_name = ''
    createForm.address = ''
    createForm.website_url = ''
    createForm.preferred_source = ''
    createForm.status = 'active'
    createForm.notes = ''
    saveMessage.value = 'Магазин создан'
    await loadShopManagement()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Не удалось создать магазин'
  } finally {
    savingIdentityId.value = null
  }
}

async function linkSource(shop: ShopListItem): Promise<void> {
  const identityId = linkTargets[shop.id]
  if (!identityId) {
    errorMessage.value = 'Выберите магазин для привязки источника'
    return
  }

  linkingShopId.value = shop.id
  errorMessage.value = ''
  saveMessage.value = ''

  try {
    await linkShopSource(Number(identityId), shop.id)
    linkTargets[shop.id] = ''
    saveMessage.value = 'Источник привязан'
    await loadShopManagement()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Не удалось привязать источник'
  } finally {
    linkingShopId.value = null
  }
}

async function unlinkSource(shop: ShopListItem): Promise<void> {
  linkingShopId.value = shop.id
  errorMessage.value = ''
  saveMessage.value = ''

  try {
    await unlinkShopSource(shop.id)
    saveMessage.value = 'Источник отвязан'
    await loadShopManagement()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Не удалось отвязать источник'
  } finally {
    linkingShopId.value = null
  }
}

watch(
  [selectedSource, selectedStatus, selectedSourceType, selectedRelationship, selectedIdentityId],
  () => {
    void loadShopManagement()
  },
)

onMounted(() => {
  void loadShopManagement()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 2xl:flex-row 2xl:items-end 2xl:justify-between">
      <div>
        <p class="inline-flex items-center gap-2 text-sm font-medium text-amber-300">
          <Icon :icon="icons.buildingStore" class="size-4" aria-hidden="true" />
          Магазины и источники
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-white">Управление источниками магазинов</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
          Реальные магазины группируют 2GIS, официальный API и HTML-каталоги. Здесь только метаданные и связи источников.
        </p>
      </div>

      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:min-w-[780px]">
        <select
          v-model="selectedSource"
          aria-label="Фильтр магазинов по источнику"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        >
          <option value="">Все источники</option>
          <option v-for="source in sourceOptions" :key="source" :value="source">{{ source }}</option>
        </select>
        <select
          v-model="selectedStatus"
          aria-label="Фильтр магазинов по scrape status"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        >
          <option value="">Все статусы</option>
          <option v-for="status in scrapeStatusOptions" :key="status" :value="status">
            {{ statusLabel(status) }}
          </option>
        </select>
        <select
          v-model="selectedSourceType"
          aria-label="Фильтр магазинов по типу источника"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        >
          <option value="">Все типы</option>
          <option v-for="option in sourceTypeOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
        <select
          v-model="selectedRelationship"
          aria-label="Фильтр магазинов по связи"
          class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
        >
          <option value="">Все связи</option>
          <option value="linked">Сгруппированные</option>
          <option value="unlinked">Без магазина</option>
        </select>
      </div>
    </div>

    <div v-if="errorMessage" class="rounded-lg border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-100">
      {{ errorMessage }}
    </div>
    <div v-if="saveMessage" class="rounded-lg border border-emerald-400/30 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100">
      {{ saveMessage }}
    </div>

    <div class="grid gap-4 md:grid-cols-4">
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="text-sm text-neutral-500">Реальные магазины</p>
        <p class="mt-3 text-3xl font-semibold text-white">{{ identities.length }}</p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="text-sm text-neutral-500">Связанные источники</p>
        <p class="mt-3 text-3xl font-semibold text-white">{{ groupedSourceCount }}</p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="text-sm text-neutral-500">Без магазина</p>
        <p class="mt-3 text-3xl font-semibold" :class="ungroupedSourceCount > 0 ? 'text-amber-200' : 'text-white'">
          {{ ungroupedSourceCount }}
        </p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="text-sm text-neutral-500">Требуют внимания</p>
        <p class="mt-3 text-3xl font-semibold" :class="failingSourceCount + heldIdentityCount > 0 ? 'text-red-200' : 'text-white'">
          {{ failingSourceCount + heldIdentityCount }}
        </p>
      </div>
    </div>

    <div class="grid gap-6 2xl:grid-cols-[minmax(420px,0.95fr)_minmax(0,1.35fr)]">
      <section class="rounded-lg border border-neutral-800 bg-neutral-900/40">
        <div class="border-b border-neutral-800 p-4">
          <h3 class="text-base font-semibold text-white">Реальные магазины</h3>
          <p class="mt-1 text-sm text-neutral-500">Группировка и приоритет источников без ручного каталога.</p>
        </div>

        <form class="grid gap-3 border-b border-neutral-800 p-4" @submit.prevent="createIdentity">
          <div class="grid gap-3 sm:grid-cols-2">
            <input
              v-model="createForm.display_name"
              aria-label="Название нового магазина"
              class="h-10 rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition focus:border-amber-400"
              placeholder="Название магазина"
            >
            <input
              v-model="createForm.website_url"
              aria-label="Сайт нового магазина"
              class="h-10 rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition focus:border-amber-400"
              placeholder="https://example.ru/catalog/"
            >
          </div>
          <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
            <select
              v-model="createForm.status"
              aria-label="Статус нового магазина"
              class="h-10 rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition focus:border-amber-400 sm:w-44"
            >
              <option v-for="option in statusOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
            <input
              v-model="createForm.notes"
              aria-label="Заметка нового магазина"
              class="h-10 min-w-0 flex-1 rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition focus:border-amber-400"
              placeholder="Заметка"
            >
            <button
              type="submit"
              class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-amber-300 px-4 text-sm font-semibold text-neutral-950 transition hover:bg-amber-200 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="savingIdentityId === 0"
            >
              <Icon :icon="icons.check" class="size-4" aria-hidden="true" />
              Создать
            </button>
          </div>
        </form>

        <div v-if="isLoading" class="p-4 text-sm text-neutral-400">Загружаем магазины...</div>
        <div v-else-if="identities.length === 0" class="p-4 text-sm text-neutral-400">Пока нет реальных магазинов.</div>
        <div v-else class="divide-y divide-neutral-800">
          <article v-for="identity in identities" :key="identity.id" class="p-4">
            <div class="flex flex-col gap-3">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p class="text-base font-semibold text-white">{{ identity.display_name }}</p>
                  <p class="mt-1 text-xs text-neutral-500">
                    {{ identity.website_url || 'Сайт не указан' }}
                  </p>
                </div>
                <span class="rounded-full border px-2.5 py-1 text-xs font-medium" :class="statusClass(identity.status)">
                  {{ statusLabel(identity.status) }}
                </span>
              </div>

              <div class="grid gap-3">
                <input
                  v-model="identityForm(identity).display_name"
                  aria-label="Название магазина"
                  class="h-10 rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition focus:border-amber-400"
                >
                <div class="grid gap-3 sm:grid-cols-2">
                  <input
                    v-model="identityForm(identity).website_url"
                    aria-label="Сайт магазина"
                    class="h-10 rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition focus:border-amber-400"
                    placeholder="Сайт магазина"
                  >
                  <select
                    v-model="identityForm(identity).status"
                    aria-label="Статус магазина"
                    class="h-10 rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition focus:border-amber-400"
                  >
                    <option v-for="option in statusOptions" :key="option.value" :value="option.value">
                      {{ option.label }}
                    </option>
                  </select>
                </div>
                <select
                  v-model="identityForm(identity).preferred_source"
                  aria-label="Приоритетный источник магазина"
                  class="h-10 rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition focus:border-amber-400"
                >
                  <option value="">Без приоритетного источника</option>
                  <option
                    v-for="shop in linkedShopsByIdentity.get(identity.id) || []"
                    :key="shop.id"
                    :value="shop.source"
                  >
                    {{ shop.source }} · {{ sourceTypeLabel(shop.source_type) }}
                  </option>
                </select>
                <textarea
                  v-model="identityForm(identity).notes"
                  aria-label="Заметки магазина"
                  rows="2"
                  class="rounded-md border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm text-white outline-none transition focus:border-amber-400"
                  placeholder="Заметки для оператора"
                />
              </div>

              <div class="flex flex-wrap gap-2">
                <span
                  v-for="shop in linkedShopsByIdentity.get(identity.id) || []"
                  :key="shop.id"
                  class="inline-flex items-center gap-2 rounded-full border border-neutral-700 bg-neutral-950 px-3 py-1 text-xs text-neutral-300"
                >
                  <span>{{ shop.source }}</span>
                  <span class="text-neutral-600">·</span>
                  <span>{{ sourceTypeLabel(shop.source_type) }}</span>
                  <button
                    type="button"
                    class="text-neutral-500 transition hover:text-red-200"
                    :disabled="linkingShopId === shop.id"
                    @click="unlinkSource(shop)"
                  >
                    отвязать
                  </button>
                </span>
              </div>

              <button
                type="button"
                class="inline-flex h-9 w-fit items-center justify-center gap-2 rounded-md border border-neutral-700 px-3 text-sm font-medium text-neutral-200 transition hover:border-amber-300 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="savingIdentityId === identity.id"
                @click="saveIdentity(identity)"
              >
                <Icon :icon="icons.check" class="size-4" aria-hidden="true" />
                Сохранить
              </button>
            </div>
          </article>
        </div>
      </section>

      <section class="rounded-lg border border-neutral-800 bg-neutral-900/40">
        <div class="flex flex-col gap-3 border-b border-neutral-800 p-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <h3 class="text-base font-semibold text-white">Записи источников</h3>
            <p class="mt-1 text-sm text-neutral-500">Источник остаётся отдельным scrape target даже после группировки.</p>
          </div>
          <select
            v-model.number="selectedIdentityId"
            aria-label="Фильтр по реальному магазину"
            class="h-10 rounded-md border border-neutral-800 bg-neutral-950 px-3 text-sm text-white outline-none transition focus:border-amber-400"
          >
            <option value="">Все магазины</option>
            <option v-for="identity in identities" :key="identity.id" :value="identity.id">
              {{ identity.display_name }}
            </option>
          </select>
        </div>

        <div v-if="isLoading" class="p-4 text-sm text-neutral-400">Загружаем источники...</div>
        <div v-else-if="shops.length === 0" class="p-4 text-sm text-neutral-400">По этим фильтрам источников нет.</div>
        <div v-else class="overflow-x-auto">
          <table class="min-w-[980px] w-full text-left text-sm">
            <thead class="border-b border-neutral-800 text-xs uppercase tracking-wide text-neutral-500">
              <tr>
                <th class="px-4 py-3 font-medium">Источник</th>
                <th class="px-4 py-3 font-medium">Магазин</th>
                <th class="px-4 py-3 font-medium">Scrape</th>
                <th class="px-4 py-3 font-medium">Расписание</th>
                <th class="px-4 py-3 font-medium">Связь</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-neutral-800">
              <tr v-for="shop in shops" :key="shop.id" class="align-top hover:bg-neutral-900/70">
                <td class="px-4 py-4">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="font-medium text-white">{{ shop.source }}</span>
                    <span class="rounded-full border px-2 py-0.5 text-xs" :class="sourceTypeClass(shop.source_type)">
                      {{ sourceTypeLabel(shop.source_type) }}
                    </span>
                    <span v-if="shop.is_preferred_source" class="rounded-full border border-amber-300/30 bg-amber-300/10 px-2 py-0.5 text-xs text-amber-200">
                      preferred
                    </span>
                  </div>
                  <p class="mt-2 max-w-[260px] truncate text-xs text-neutral-500">{{ shop.source_id }}</p>
                </td>
                <td class="px-4 py-4">
                  <p class="font-medium text-white">{{ shop.name }}</p>
                  <p class="mt-1 max-w-[280px] truncate text-xs text-neutral-500">{{ shop.address || shop.url || '-' }}</p>
                </td>
                <td class="px-4 py-4">
                  <span class="rounded-full border px-2.5 py-1 text-xs font-medium" :class="statusClass(shop.scrape_status)">
                    {{ statusLabel(shop.scrape_status) }}
                  </span>
                  <p class="mt-2 text-xs text-neutral-500">ошибок: {{ shop.error_count }}</p>
                </td>
                <td class="px-4 py-4 text-xs text-neutral-400">
                  <p>последний: {{ formatDateTime(shop.last_scraped_at) }}</p>
                  <p class="mt-1">следующий: {{ formatDateTime(shop.next_scrape_at) }}</p>
                </td>
                <td class="px-4 py-4">
                  <div v-if="shop.identity" class="flex flex-col gap-2">
                    <span class="text-sm text-white">{{ shop.identity.display_name }}</span>
                    <button
                      type="button"
                      class="inline-flex h-8 w-fit items-center rounded-md border border-neutral-700 px-3 text-xs font-medium text-neutral-300 transition hover:border-red-300 hover:text-red-200 disabled:opacity-50"
                      :disabled="linkingShopId === shop.id"
                      @click="unlinkSource(shop)"
                    >
                      Отвязать
                    </button>
                  </div>
                  <div v-else class="flex flex-col gap-2">
                    <select
                      v-model.number="linkTargets[shop.id]"
                      :aria-label="`Магазин для источника ${shop.source_id}`"
                      class="h-9 rounded-md border border-neutral-800 bg-neutral-950 px-2 text-xs text-white outline-none transition focus:border-amber-400"
                    >
                      <option value="">Выбрать магазин</option>
                      <option v-for="identity in identities" :key="identity.id" :value="identity.id">
                        {{ identity.display_name }}
                      </option>
                    </select>
                    <button
                      type="button"
                      class="inline-flex h-8 w-fit items-center gap-2 rounded-md border border-neutral-700 px-3 text-xs font-medium text-neutral-300 transition hover:border-amber-300 hover:text-white disabled:opacity-50"
                      :disabled="linkingShopId === shop.id"
                      @click="linkSource(shop)"
                    >
                      <Icon :icon="icons.link" class="size-3.5" aria-hidden="true" />
                      Привязать
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </section>
</template>
