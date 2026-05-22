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
const isCreateModalOpen = ref(false)
const editingIdentity = ref<ShopIdentity | null>(null)
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
    return 'Не запланировано'
  }

  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function placeholder(value: string | null | undefined, fallback: string): string {
  const normalized = value?.trim()
  return normalized || fallback
}

function linkedSourceSummary(identity: ShopIdentity): string {
  const linked = linkedShopsByIdentity.value.get(identity.id) || []
  if (linked.length === 0) {
    return 'Источники не привязаны'
  }

  return linked.map((shop) => `${shop.source} · ${sourceTypeLabel(shop.source_type)}`).join(', ')
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

function resetCreateForm(): void {
  createForm.display_name = ''
  createForm.address = ''
  createForm.website_url = ''
  createForm.preferred_source = ''
  createForm.status = 'active'
  createForm.notes = ''
  createForm.locked_fields = null
}

function openCreateModal(): void {
  resetCreateForm()
  errorMessage.value = ''
  saveMessage.value = ''
  isCreateModalOpen.value = true
}

function closeCreateModal(): void {
  isCreateModalOpen.value = false
}

function openEditModal(identity: ShopIdentity): void {
  void identityForm(identity)
  editingIdentity.value = identity
  errorMessage.value = ''
  saveMessage.value = ''
}

function closeEditModal(): void {
  editingIdentity.value = null
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
    closeEditModal()
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
    resetCreateForm()
    closeCreateModal()
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
    <div>
      <div>
        <p class="inline-flex items-center gap-2 text-sm font-medium text-amber-300">
          <Icon :icon="icons.buildingStore" class="size-4" aria-hidden="true" />
          Магазины и источники
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-white">Управление магазинами</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
          Магазины объединяют source-записи из 2GIS, официальных API и HTML-каталогов. Здесь только метаданные, статусы и связи источников.
        </p>
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
        <p class="inline-flex items-center gap-2 text-sm text-neutral-500">
          <Icon :icon="icons.buildingStore" class="size-4" aria-hidden="true" />
          Магазины
        </p>
        <p class="mt-3 text-3xl font-semibold text-white">{{ identities.length }}</p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="inline-flex items-center gap-2 text-sm text-neutral-500">
          <Icon :icon="icons.link" class="size-4" aria-hidden="true" />
          Связанные источники
        </p>
        <p class="mt-3 text-3xl font-semibold text-white">{{ groupedSourceCount }}</p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="inline-flex items-center gap-2 text-sm text-neutral-500">
          <Icon :icon="icons.linkOff" class="size-4" aria-hidden="true" />
          Без магазина
        </p>
        <p class="mt-3 text-3xl font-semibold" :class="ungroupedSourceCount > 0 ? 'text-amber-200' : 'text-white'">
          {{ ungroupedSourceCount }}
        </p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="inline-flex items-center gap-2 text-sm text-neutral-500">
          <Icon :icon="icons.alertTriangle" class="size-4" aria-hidden="true" />
          Требуют внимания
        </p>
        <p class="mt-3 text-3xl font-semibold" :class="failingSourceCount + heldIdentityCount > 0 ? 'text-red-200' : 'text-white'">
          {{ failingSourceCount + heldIdentityCount }}
        </p>
      </div>
    </div>

    <section class="space-y-3">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h3 class="text-base font-semibold text-white">Магазины</h3>
          <p class="mt-1 text-sm text-neutral-500">Карточки магазинов, их статус и приоритетный источник.</p>
        </div>
        <button
          type="button"
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-amber-300 px-4 text-sm font-semibold text-neutral-950 transition hover:bg-amber-200"
          @click="openCreateModal"
        >
          <Icon :icon="icons.plus" class="size-4" aria-hidden="true" />
          Создать
        </button>
      </div>

      <div v-if="isLoading" class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4 text-sm text-neutral-400">
        Загружаем магазины...
      </div>
      <div v-else-if="identities.length === 0" class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-8 text-center text-sm text-neutral-500">
        Магазины ещё не созданы.
      </div>
      <div v-else class="overflow-x-auto rounded-lg border border-neutral-800 bg-neutral-900/40">
        <table class="w-full min-w-[920px] text-left text-sm">
          <thead class="border-b border-neutral-800 text-xs uppercase tracking-wide text-neutral-500">
            <tr>
              <th class="px-4 py-3 font-medium">Магазин</th>
              <th class="px-4 py-3 font-medium">Сайт</th>
              <th class="px-4 py-3 font-medium">Статус</th>
              <th class="px-4 py-3 font-medium">Источники</th>
              <th class="px-4 py-3 font-medium">Заметки</th>
              <th class="px-4 py-3 font-medium">Действия</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-neutral-800">
            <tr v-for="identity in identities" :key="identity.id" class="align-top hover:bg-neutral-900/70">
              <td class="px-4 py-4">
                <p class="font-medium text-white">{{ identity.display_name }}</p>
                <p class="mt-1 text-xs text-neutral-500">{{ placeholder(identity.address, 'Адрес не указан') }}</p>
              </td>
              <td class="px-4 py-4">
                <span class="text-neutral-300">{{ placeholder(identity.website_url, 'Сайт не указан') }}</span>
              </td>
              <td class="px-4 py-4">
                <span class="rounded-full border px-2.5 py-1 text-xs font-medium" :class="statusClass(identity.status)">
                  {{ statusLabel(identity.status) }}
                </span>
              </td>
              <td class="px-4 py-4">
                <p class="max-w-[280px] text-neutral-300">{{ linkedSourceSummary(identity) }}</p>
                <p class="mt-1 text-xs text-neutral-500">
                  preferred: {{ identity.preferred_source || 'не выбран' }}
                </p>
              </td>
              <td class="px-4 py-4">
                <p class="max-w-[260px] text-neutral-400">{{ placeholder(identity.notes, 'Заметок нет') }}</p>
              </td>
              <td class="px-4 py-4">
                <button
                  type="button"
                  class="inline-flex h-8 items-center gap-2 rounded-md border border-amber-400/40 bg-amber-400/10 px-3 text-xs font-medium text-amber-100 transition hover:border-amber-300 hover:bg-amber-300/15 hover:text-amber-50"
                  @click="openEditModal(identity)"
                >
                  <Icon :icon="icons.pencil" class="size-3.5" aria-hidden="true" />
                  Редактировать
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="space-y-3">
      <div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h3 class="text-base font-semibold text-white">Источники</h3>
          <p class="mt-1 text-sm text-neutral-500">Отдельные scrape targets: 2GIS, официальный API и официальный HTML-каталог.</p>
        </div>
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:min-w-[920px] xl:grid-cols-5">
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
          <select
            v-model.number="selectedIdentityId"
            aria-label="Фильтр по магазину"
            class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
          >
            <option value="">Все магазины</option>
            <option v-for="identity in identities" :key="identity.id" :value="identity.id">
              {{ identity.display_name }}
            </option>
          </select>
        </div>
      </div>

      <div v-if="isLoading" class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4 text-sm text-neutral-400">
        Загружаем источники...
      </div>
      <div v-else-if="shops.length === 0" class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-8 text-center text-sm text-neutral-500">
        По этим фильтрам источников нет.
      </div>
      <div v-else class="overflow-x-auto rounded-lg border border-neutral-800 bg-neutral-900/40">
        <table class="w-full min-w-[1160px] text-left text-sm">
          <thead class="border-b border-neutral-800 text-xs uppercase tracking-wide text-neutral-500">
            <tr>
              <th class="px-4 py-3 font-medium">Источник</th>
              <th class="px-4 py-3 font-medium">Source ID / URL</th>
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
                <p class="mt-2 text-xs text-neutral-500">{{ shop.name }}</p>
              </td>
              <td class="px-4 py-4">
                <p class="max-w-[280px] truncate text-neutral-300" :title="shop.url || shop.source_id">
                  {{ shop.url || shop.source_id }}
                </p>
                <p class="mt-1 max-w-[280px] truncate text-xs text-neutral-500" :title="shop.source_id">
                  {{ shop.source_id }}
                </p>
              </td>
              <td class="px-4 py-4">
                <p class="font-medium text-white">{{ placeholder(shop.identity?.display_name, 'Не привязан') }}</p>
                <p class="mt-1 max-w-[240px] truncate text-xs text-neutral-500">
                  {{ placeholder(shop.address, 'Адрес не указан') }}
                </p>
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
                    class="h-9 rounded-md border border-neutral-800 bg-neutral-950 px-2 text-xs text-white outline-none transition focus:border-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
                    :disabled="linkingShopId === shop.id"
                    @change="linkSource(shop)"
                  >
                    <option value="">Выбрать магазин</option>
                    <option v-for="identity in identities" :key="identity.id" :value="identity.id">
                      {{ identity.display_name }}
                    </option>
                  </select>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="isCreateModalOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-neutral-950/80 p-4">
      <form class="w-full max-w-2xl rounded-lg border border-neutral-800 bg-neutral-950 p-5 shadow-2xl" @submit.prevent="createIdentity">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h3 class="text-lg font-semibold text-white">Создать магазин</h3>
            <p class="mt-1 text-sm text-neutral-500">Карточка магазина появится без ручного каталога и цен.</p>
          </div>
          <button
            type="button"
            class="inline-flex size-9 items-center justify-center rounded-md text-neutral-400 transition hover:bg-neutral-900 hover:text-white"
            aria-label="Закрыть окно создания магазина"
            @click="closeCreateModal"
          >
            <Icon :icon="icons.x" class="size-5" aria-hidden="true" />
          </button>
        </div>

        <div class="mt-5 grid gap-3 sm:grid-cols-2">
          <input
            v-model="createForm.display_name"
            aria-label="Название нового магазина"
            class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
            placeholder="Название магазина"
          >
          <input
            v-model="createForm.website_url"
            aria-label="Сайт нового магазина"
            class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
            placeholder="https://example.ru/catalog/"
          >
          <input
            v-model="createForm.address"
            aria-label="Адрес нового магазина"
            class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
            placeholder="Адрес"
          >
          <select
            v-model="createForm.status"
            aria-label="Статус нового магазина"
            class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
          >
            <option v-for="option in statusOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </div>
        <textarea
          v-model="createForm.notes"
          aria-label="Заметка нового магазина"
          rows="3"
          class="mt-3 w-full rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-white outline-none transition focus:border-amber-400"
          placeholder="Заметки для оператора"
        />
        <div class="mt-5 flex justify-end gap-3">
          <button type="button" class="h-10 rounded-md border border-neutral-700 px-4 text-sm font-medium text-neutral-300 transition hover:border-neutral-500 hover:text-white" @click="closeCreateModal">
            Отмена
          </button>
          <button
            type="submit"
            class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-amber-300 px-4 text-sm font-semibold text-neutral-950 transition hover:bg-amber-200 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="savingIdentityId === 0"
          >
            <Icon :icon="icons.plus" class="size-4" aria-hidden="true" />
            Создать
          </button>
        </div>
      </form>
    </div>

    <div v-if="editingIdentity" class="fixed inset-0 z-50 flex items-center justify-center bg-neutral-950/80 p-4">
      <form class="w-full max-w-2xl rounded-lg border border-neutral-800 bg-neutral-950 p-5 shadow-2xl" @submit.prevent="saveIdentity(editingIdentity)">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h3 class="text-lg font-semibold text-white">Редактировать магазин</h3>
            <p class="mt-1 text-sm text-neutral-500">{{ editingIdentity.display_name }}</p>
          </div>
          <button
            type="button"
            class="inline-flex size-9 items-center justify-center rounded-md text-neutral-400 transition hover:bg-neutral-900 hover:text-white"
            aria-label="Закрыть окно редактирования магазина"
            @click="closeEditModal"
          >
            <Icon :icon="icons.x" class="size-5" aria-hidden="true" />
          </button>
        </div>

        <div class="mt-5 grid gap-3 sm:grid-cols-2">
          <input
            v-model="identityForm(editingIdentity).display_name"
            aria-label="Название магазина"
            class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
          >
          <input
            v-model="identityForm(editingIdentity).website_url"
            aria-label="Сайт магазина"
            class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
            placeholder="Сайт магазина"
          >
          <input
            v-model="identityForm(editingIdentity).address"
            aria-label="Адрес магазина"
            class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
            placeholder="Адрес"
          >
          <select
            v-model="identityForm(editingIdentity).status"
            aria-label="Статус магазина"
            class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400"
          >
            <option v-for="option in statusOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <select
            v-model="identityForm(editingIdentity).preferred_source"
            aria-label="Приоритетный источник магазина"
            class="h-10 rounded-md border border-neutral-800 bg-neutral-900 px-3 text-sm text-white outline-none transition focus:border-amber-400 sm:col-span-2"
          >
            <option value="">Без приоритетного источника</option>
            <option
              v-for="shop in linkedShopsByIdentity.get(editingIdentity.id) || []"
              :key="shop.id"
              :value="shop.source"
            >
              {{ shop.source }} · {{ sourceTypeLabel(shop.source_type) }}
            </option>
          </select>
        </div>
        <textarea
          v-model="identityForm(editingIdentity).notes"
          aria-label="Заметки магазина"
          rows="3"
          class="mt-3 w-full rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-white outline-none transition focus:border-amber-400"
          placeholder="Заметки для оператора"
        />
        <div class="mt-5 flex justify-end gap-3">
          <button type="button" class="h-10 rounded-md border border-neutral-700 px-4 text-sm font-medium text-neutral-300 transition hover:border-neutral-500 hover:text-white" @click="closeEditModal">
            Отмена
          </button>
          <button
            type="submit"
            class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-amber-300 px-4 text-sm font-semibold text-neutral-950 transition hover:bg-amber-200 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="savingIdentityId === editingIdentity.id"
          >
            <Icon :icon="icons.check" class="size-4" aria-hidden="true" />
            Сохранить
          </button>
        </div>
      </form>
    </div>
  </section>
</template>
