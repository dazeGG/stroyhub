<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

import { icons } from './lib/icons'

const navSections = [
  {
    label: 'Работа',
    items: [
      { label: 'Качество каталога', to: '/', icon: icons.layoutDashboard },
      { label: 'Можно принять', to: '/workflows/queues/auto_acceptable', icon: icons.check },
      { label: 'Проверка', to: '/workflows/queues/review_needed', icon: icons.listCheck },
      { label: 'Похожие товары', to: '/workflows/queues/possible_duplicates', icon: icons.gitCompare },
      { label: 'Проблемы данных', to: '/workflows/queues/data_problems', icon: icons.alertTriangle },
    ],
  },
  {
    label: 'Каталог',
    items: [
      { label: 'Нормализованный каталог', to: '/canonical-products', icon: icons.tags },
      { label: 'Исходные товары', to: '/products', icon: icons.package },
      { label: 'Категоризация', to: '/categories/quality', icon: icons.category },
    ],
  },
  {
    label: 'Источники',
    items: [
      { label: 'Источники товаров', to: '/shops', icon: icons.buildingStore },
      { label: 'Новые источники', to: '/shops/candidates', icon: icons.databaseImport },
      { label: 'Загрузки', to: '/scrapes', icon: icons.activity },
    ],
  },
  {
    label: 'Техническое',
    items: [
      { label: 'Категории', to: '/categories', icon: icons.category },
      { label: 'Очередь нормализации', to: '/products/normalization', icon: icons.listCheck },
      { label: 'Сверка связей', to: '/matches', icon: icons.gitCompare },
    ],
  },
]
const mobileNavItems = navSections.flatMap((section) => section.items)

const route = useRoute()
const isFullPage = computed(() => route.meta.fullPage === true)
const toasterOptions = { max: 3 }
</script>

<template>
  <UApp :toaster="toasterOptions">
    <div class="min-h-screen bg-neutral-950 text-neutral-100">
      <RouterView v-if="isFullPage" />

      <template v-else>
        <aside class="fixed inset-y-0 left-0 hidden w-64 overflow-y-auto border-r border-neutral-800 bg-neutral-950/95 px-5 py-6 lg:block">
          <RouterLink to="/" class="flex items-baseline gap-3">
            <p class="text-sm font-bold uppercase tracking-wide text-amber-300">StroyHub</p>
            <h1 class="text-xs font-medium text-neutral-400">Админка</h1>
          </RouterLink>

          <nav class="mt-8 flex flex-col gap-5">
            <section v-for="section in navSections" :key="section.label">
              <p class="px-3 text-xs font-semibold uppercase tracking-wide text-neutral-600">
                {{ section.label }}
              </p>
              <div class="mt-2 flex flex-col gap-1">
                <RouterLink
                  v-for="item in section.items"
                  :key="item.to"
                  :to="item.to"
                  class="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-neutral-300 transition hover:bg-neutral-900 hover:text-white"
                  active-class="bg-neutral-800 text-white"
                >
                  <Icon :icon="item.icon" class="size-4 text-neutral-500" aria-hidden="true" />
                  {{ item.label }}
                </RouterLink>
              </div>
            </section>
          </nav>
        </aside>

        <div class="lg:pl-64">
          <nav
            class="sticky top-0 z-10 flex gap-2 overflow-x-auto border-b border-neutral-800 bg-neutral-950/90 px-4 py-3 backdrop-blur sm:px-6 lg:hidden"
          >
            <RouterLink
              v-for="item in mobileNavItems"
              :key="item.to"
              :to="item.to"
              class="inline-flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-neutral-300 transition hover:bg-neutral-900 hover:text-white"
              active-class="bg-neutral-800 text-white"
            >
              <Icon :icon="item.icon" class="size-4 text-neutral-500" aria-hidden="true" />
              {{ item.label }}
            </RouterLink>
          </nav>

          <main class="px-4 py-6 sm:px-6 lg:px-8">
            <RouterView />
          </main>
        </div>
      </template>
    </div>
  </UApp>
</template>
