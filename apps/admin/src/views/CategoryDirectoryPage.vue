<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { useToast } from '@nuxt/ui/composables'
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { fetchCategories, type CategoryTreeItem } from '../lib/api'
import { icons } from '../lib/icons'
import { messageFromError, toastError } from '../lib/notifications'

interface CategoryDirectoryRow {
  id: number
  slug: string
  name: string
  parentName: string
  productCount: number
  childCount: number
  depth: number
  isRoot: boolean
}

const categories = ref<CategoryTreeItem[]>([])
const searchQuery = ref('')
const expandedRootIds = ref<Set<number>>(new Set())
const isLoading = ref(false)
const errorMessage = ref('')
const toast = useToast()

const directoryRows = computed<CategoryDirectoryRow[]>(() => {
  const rows: CategoryDirectoryRow[] = []

  function walk(items: CategoryTreeItem[], parentName: string, depth: number): void {
    for (const item of items) {
      rows.push({
        id: item.id,
        slug: item.slug,
        name: item.name,
        parentName,
        productCount: item.product_count,
        childCount: item.children.length,
        depth,
        isRoot: depth === 0,
      })
      walk(item.children, item.name, depth + 1)
    }
  }

  walk(categories.value, '-', 0)
  return rows
})

const rootCount = computed(() => categories.value.length)
const childCount = computed(() => directoryRows.value.filter((row) => !row.isRoot).length)
const assignedProductCount = computed(() => {
  return directoryRows.value
    .filter((row) => !row.isRoot)
    .reduce((total, row) => total + row.productCount, 0)
})
const emptyLeafCount = computed(() => {
  return directoryRows.value.filter((row) => !row.isRoot && row.productCount === 0).length
})

const filteredCategoryGroups = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()

  if (!query) {
    return categories.value
  }

  return categories.value
    .map((category) => {
      const rootMatches = [category.name, category.slug].some((value) => value.toLowerCase().includes(query))
      const children = category.children.filter((child) => {
        return [child.name, child.slug, category.name].some((value) => value.toLowerCase().includes(query))
      })

      return {
        ...category,
        children: rootMatches ? category.children : children,
      }
    })
    .filter((category) => {
      return [category.name, category.slug].some((value) => value.toLowerCase().includes(query)) || category.children.length > 0
    })
})

function isCategoryExpanded(category: CategoryTreeItem): boolean {
  if (searchQuery.value.trim()) {
    return true
  }

  return expandedRootIds.value.has(category.id)
}

function toggleCategory(category: CategoryTreeItem): void {
  if (category.children.length === 0) {
    return
  }

  const next = new Set(expandedRootIds.value)
  if (next.has(category.id)) {
    next.delete(category.id)
  } else {
    next.add(category.id)
  }
  expandedRootIds.value = next
}

async function loadCategories(): Promise<void> {
  isLoading.value = true
  errorMessage.value = ''

  try {
    const response = await fetchCategories()
    categories.value = response.items
  } catch (error) {
    errorMessage.value = messageFromError(error, 'Не удалось загрузить категории')
    toastError(toast, 'Не удалось загрузить категории', error, 'Не удалось загрузить категории')
    categories.value = []
  } finally {
    isLoading.value = false
  }
}

onMounted(() => {
  void loadCategories()
})
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 2xl:flex-row 2xl:items-end 2xl:justify-between">
      <div>
        <p class="inline-flex items-center gap-2 text-sm font-medium text-admin-link">
          <Icon :icon="icons.category" class="size-4" aria-hidden="true" />
          Категории
        </p>
        <h2 class="mt-2 text-2xl font-semibold text-admin-text">Дерево нормализованных категорий</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-admin-text-muted">
          Два уровня: родительские разделы группируют каталог, дочерние категории получают товары.
        </p>
      </div>

      <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
        <label class="relative min-w-0 sm:w-72">
          <Icon
            :icon="icons.search"
            class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-admin-text-faint"
            aria-hidden="true"
          />
          <input
            v-model="searchQuery"
            class="h-10 w-full rounded-md border border-admin-border bg-admin-surface-muted pl-9 pr-3 text-sm text-admin-text outline-none transition placeholder:text-admin-text-faint focus:border-admin-focus"
            placeholder="Поиск категории"
            type="search"
          />
        </label>
        <RouterLink
          class="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-admin-border-strong bg-admin-surface-muted px-3 text-sm font-medium text-admin-link transition hover:border-admin-primary"
          data-testid="category-quality-link"
          :to="{ name: 'category-quality' }"
        >
          <Icon :icon="icons.reportAnalytics" class="size-4" aria-hidden="true" />
          Проверка качества
        </RouterLink>
      </div>
    </div>

    <div class="grid gap-4 md:grid-cols-4">
      <div class="rounded-lg border border-admin-border bg-admin-surface p-5">
        <p class="inline-flex items-center gap-2 text-sm text-admin-text-faint">
          <Icon :icon="icons.category" class="size-4" aria-hidden="true" />
          Разделов
        </p>
        <p class="mt-3 text-3xl font-semibold text-admin-text">{{ rootCount }}</p>
      </div>
      <div class="rounded-lg border border-admin-border bg-admin-surface p-5">
        <p class="inline-flex items-center gap-2 text-sm text-admin-text-faint">
          <Icon :icon="icons.tags" class="size-4" aria-hidden="true" />
          Дочерних
        </p>
        <p class="mt-3 text-3xl font-semibold text-admin-text">{{ childCount }}</p>
      </div>
      <div class="rounded-lg border border-admin-border bg-admin-surface p-5">
        <p class="inline-flex items-center gap-2 text-sm text-admin-text-faint">
          <Icon :icon="icons.shoppingBag" class="size-4" aria-hidden="true" />
          Товаров
        </p>
        <p class="mt-3 text-3xl font-semibold text-admin-text">{{ assignedProductCount }}</p>
      </div>
      <div class="rounded-lg border border-admin-border bg-admin-surface p-5">
        <p class="inline-flex items-center gap-2 text-sm text-admin-text-faint">
          <Icon :icon="icons.alertTriangle" class="size-4" aria-hidden="true" />
          Пустых
        </p>
        <p class="mt-3 text-3xl font-semibold text-admin-text">{{ emptyLeafCount }}</p>
      </div>
    </div>

    <div class="rounded-lg border border-admin-border bg-admin-surface">
      <div v-if="isLoading" class="px-4 py-14 text-center text-sm text-admin-text-faint">
        <Icon :icon="icons.category" class="mx-auto mb-3 size-6 text-admin-text-faint" aria-hidden="true" />
        Загружаем категории...
      </div>

      <div
        v-else-if="filteredCategoryGroups.length === 0"
        class="px-4 py-14 text-center text-sm text-admin-text-faint"
      >
        <Icon :icon="icons.search" class="mx-auto mb-3 size-6 text-admin-text-faint" aria-hidden="true" />
        Категорий по этому поиску нет.
      </div>

      <div v-else class="divide-y divide-admin-border">
        <section
          v-for="category in filteredCategoryGroups"
          :key="category.id"
          class="bg-admin-surface-subtle"
          data-testid="category-directory-row"
        >
          <div
            class="grid w-full gap-3 px-4 py-4 text-left text-sm transition hover:bg-admin-surface-hover md:grid-cols-[minmax(260px,1fr)_minmax(150px,220px)_120px_150px] md:gap-x-6"
          >
            <button
              type="button"
              class="flex min-w-0 items-start gap-3 text-left"
              :aria-expanded="isCategoryExpanded(category)"
              :aria-controls="`category-children-${category.id}`"
              @click="toggleCategory(category)"
            >
              <span
                class="mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-md border text-admin-text-muted"
                :class="category.children.length > 0 ? 'border-admin-border-strong bg-admin-surface-muted' : 'border-admin-border bg-admin-surface text-admin-text-faint'"
              >
                <Icon
                  :icon="icons.chevronRight"
                  class="size-4 transition"
                  :class="isCategoryExpanded(category) ? 'rotate-90' : ''"
                  aria-hidden="true"
                />
              </span>
              <div class="min-w-0">
                <p class="truncate text-base font-semibold text-admin-text" :title="category.name">{{ category.name }}</p>
              </div>
            </button>
            <div class="min-w-0 md:text-right">
              <p class="text-xs uppercase tracking-wide text-admin-text-faint">Slug</p>
              <p class="mt-1 truncate font-mono text-xs text-admin-text-muted" :title="category.slug">{{ category.slug }}</p>
            </div>
            <div class="md:text-right">
              <p class="text-xs uppercase tracking-wide text-admin-text-faint">Товары</p>
              <p class="mt-1 font-semibold text-admin-text">{{ category.product_count }}</p>
            </div>
            <div class="flex items-start justify-start md:justify-end">
              <RouterLink
                :to="{ path: '/products', query: { category: category.id } }"
                class="inline-flex h-8 items-center gap-2 whitespace-nowrap rounded-md border border-admin-border-strong px-3 text-xs font-medium text-admin-text-muted transition hover:border-admin-primary hover:text-admin-link-hover"
                aria-label="Открыть исходные товары категории"
                title="Исходные товары"
                @click.stop
              >
                <Icon :icon="icons.package" class="size-3.5" aria-hidden="true" />
                Исходные товары
              </RouterLink>
            </div>
          </div>

          <div
            v-if="category.children.length > 0 && isCategoryExpanded(category)"
            :id="`category-children-${category.id}`"
            class="pb-3"
          >
            <div
              v-for="child in category.children"
              :key="child.id"
              class="mx-4 grid gap-3 border-t border-admin-border px-0 py-3 text-sm md:grid-cols-[minmax(260px,1fr)_minmax(150px,220px)_120px_150px] md:gap-x-6"
              data-testid="category-directory-row"
            >
              <div class="min-w-0 pl-10 md:pl-12">
                <p class="truncate font-medium text-admin-text" :title="child.name">{{ child.name }}</p>
              </div>
              <p class="min-w-0 truncate font-mono text-xs text-admin-text-muted md:text-right" :title="child.slug">
                {{ child.slug }}
              </p>
              <p class="font-medium text-admin-text md:text-right">{{ child.product_count }}</p>
              <div class="flex justify-start md:justify-end">
                <RouterLink
                  :to="{ path: '/products', query: { category: child.id } }"
                  class="inline-flex h-8 items-center gap-2 whitespace-nowrap rounded-md border border-admin-border-strong px-3 text-xs font-medium text-admin-text-muted transition hover:border-admin-primary hover:text-admin-link-hover"
                  aria-label="Открыть исходные товары категории"
                  title="Исходные товары"
                >
                  <Icon :icon="icons.package" class="size-3.5" aria-hidden="true" />
                  Исходные товары
                </RouterLink>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  </section>
</template>
