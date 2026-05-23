<script setup lang="ts">
import { Icon } from '@iconify/vue'
import { RouterLink } from 'vue-router'

import { icons } from '../lib/icons'
</script>

<template>
  <section class="space-y-6">
    <div class="max-w-3xl">
      <p class="inline-flex items-center gap-2 text-sm font-medium text-amber-300">
        <Icon :icon="icons.layoutDashboard" class="size-4" aria-hidden="true" />
        Дашборд
      </p>
      <h2 class="mt-2 text-2xl font-semibold text-white">Дашборд в разработке</h2>
      <p class="mt-2 text-sm leading-6 text-neutral-400">
        Здесь будет обзор состояния источников, свежести цен, покрытия категорий и очередей загрузки.
      </p>
    </div>

    <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-6">
      <p class="text-sm font-medium text-neutral-200">Пока можно перейти в рабочие разделы:</p>
      <div class="mt-4 flex flex-wrap gap-2">
        <RouterLink
          to="/products"
          class="inline-flex h-9 items-center gap-2 rounded-md border border-neutral-700 px-3 text-sm font-medium text-neutral-300 transition hover:border-amber-300 hover:text-amber-100"
        >
          <Icon :icon="icons.package" class="size-4" aria-hidden="true" />
          Исходные товары
        </RouterLink>
        <RouterLink
          to="/shops"
          class="inline-flex h-9 items-center gap-2 rounded-md border border-neutral-700 px-3 text-sm font-medium text-neutral-300 transition hover:border-amber-300 hover:text-amber-100"
        >
          <Icon :icon="icons.buildingStore" class="size-4" aria-hidden="true" />
          Магазины
        </RouterLink>
        <RouterLink
          to="/categories"
          class="inline-flex h-9 items-center gap-2 rounded-md border border-neutral-700 px-3 text-sm font-medium text-neutral-300 transition hover:border-amber-300 hover:text-amber-100"
        >
          <Icon :icon="icons.category" class="size-4" aria-hidden="true" />
          Категории
        </RouterLink>
      </div>
    </div>
  </section>
</template>
