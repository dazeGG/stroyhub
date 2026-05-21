<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

import { icons } from './lib/icons'

const navItems = [
  { label: 'Каталог', to: '/', icon: icons.package },
  { label: 'История цен', to: '/prices', icon: icons.history },
  { label: 'Скрейпы', to: '/scrapes', icon: icons.activity },
  { label: 'Категории', to: '/categories', icon: icons.category },
  { label: 'Матчинг', to: '/matches', icon: icons.gitCompare },
  { label: 'Помощь', to: '/help', icon: icons.helpCircle },
]

const route = useRoute()
const isFullPage = computed(() => route.meta.fullPage === true)
</script>

<template>
  <UApp>
    <div class="min-h-screen bg-neutral-950 text-neutral-100">
      <RouterView v-if="isFullPage" />

      <template v-else>
        <aside class="fixed inset-y-0 left-0 hidden w-64 border-r border-neutral-800 bg-neutral-950/95 px-5 py-6 lg:block">
          <RouterLink to="/" class="block">
            <p class="text-xs font-semibold uppercase tracking-wide text-amber-300">StroyHub</p>
            <h1 class="mt-2 text-xl font-semibold text-white">Админка</h1>
          </RouterLink>

          <nav class="mt-10 flex flex-col gap-1">
            <RouterLink
              v-for="item in navItems"
              :key="item.to"
              :to="item.to"
              class="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-neutral-300 transition hover:bg-neutral-900 hover:text-white"
              active-class="bg-neutral-800 text-white"
            >
              <Icon :icon="item.icon" class="size-4 text-neutral-500" aria-hidden="true" />
              {{ item.label }}
            </RouterLink>
          </nav>
        </aside>

        <div class="lg:pl-64">
          <header class="sticky top-0 z-10 border-b border-neutral-800 bg-neutral-950/90 backdrop-blur">
            <div class="flex min-h-16 items-center justify-between px-4 sm:px-6 lg:px-8">
              <div>
                <p class="text-xs font-medium uppercase tracking-wide text-neutral-500">M12 админка</p>
                <p class="text-sm text-neutral-300">Данные по стройматериалам Якутска</p>
              </div>
              <UBadge color="neutral" variant="subtle">Локальный API</UBadge>
            </div>
            <nav class="flex gap-2 overflow-x-auto border-t border-neutral-900 px-4 pb-3 sm:px-6 lg:hidden">
              <RouterLink
                v-for="item in navItems"
                :key="item.to"
                :to="item.to"
                class="inline-flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-neutral-300 transition hover:bg-neutral-900 hover:text-white"
                active-class="bg-neutral-800 text-white"
              >
                <Icon :icon="item.icon" class="size-4 text-neutral-500" aria-hidden="true" />
                {{ item.label }}
              </RouterLink>
            </nav>
          </header>

          <main class="px-4 py-6 sm:px-6 lg:px-8">
            <RouterView />
          </main>
        </div>
      </template>
    </div>
  </UApp>
</template>
