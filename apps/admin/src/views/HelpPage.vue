<script setup lang="ts">
import { Icon } from '@iconify/vue'
import MarkdownIt from 'markdown-it'
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { icons } from '../lib/icons'

const docs = [
  {
    slug: 'overview',
    title: 'Обзор',
    description: 'Как устроена админка и когда заводить issue.',
    icon: icons.files,
  },
  {
    slug: 'catalog',
    title: 'Каталог',
    description: 'Проверка исходных карточек, категорий и последних цен.',
    icon: icons.package,
  },
  {
    slug: 'prices',
    title: 'История цен',
    description: 'Price snapshots, повторы и null-price наблюдения.',
    icon: icons.history,
  },
  {
    slug: 'scrapes',
    title: 'Скрейпы',
    description: 'Статусы магазинов, recent runs и ошибки источников.',
    icon: icons.activity,
  },
  {
    slug: 'categories',
    title: 'Категории',
    description: 'Unmatched группы, representative titles и экспорт в issue.',
    icon: icons.category,
  },
  {
    slug: 'matches',
    title: 'Матчинг',
    description: 'Read-only кандидаты, confidence и reason tokens.',
    icon: icons.gitCompare,
  },
]

const markdownFiles = import.meta.glob('../help/*.md', {
  eager: true,
  import: 'default',
  query: '?raw',
}) as Record<string, string>

const markdown = new MarkdownIt({
  breaks: true,
  html: false,
  linkify: true,
})

const selectedSlug = ref(docs[0].slug)

const selectedDoc = computed(() => {
  return docs.find((doc) => doc.slug === selectedSlug.value) || docs[0]
})

const renderedContent = computed(() => {
  const raw = markdownFiles[`../help/${selectedDoc.value.slug}.md`] || ''
  return markdown.render(raw)
})
</script>

<template>
  <section class="min-h-screen bg-neutral-950 px-4 py-5 text-neutral-100 sm:px-6 lg:px-8">
    <div class="mx-auto max-w-6xl space-y-7">
      <header class="flex flex-col gap-5 border-b border-neutral-800 pb-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p class="inline-flex items-center gap-2 text-sm font-medium text-amber-300">
            <Icon :icon="icons.helpCircle" class="size-4" aria-hidden="true" />
            Помощь
          </p>
          <h2 class="mt-2 text-2xl font-semibold text-white">Документация по админке</h2>
          <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
            Markdown-разделы с примерами экранов, рабочими сценариями и правилами для follow-up issues.
          </p>
        </div>

        <RouterLink
          to="/"
          class="inline-flex w-fit items-center rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm font-medium text-neutral-100 transition hover:border-amber-300/60 hover:text-amber-200"
        >
          <Icon :icon="icons.arrowLeft" class="mr-2 size-4" aria-hidden="true" />
          Назад в админку
        </RouterLink>
      </header>

      <nav class="flex gap-2 overflow-x-auto pb-1">
        <button
          v-for="doc in docs"
          :key="doc.slug"
          :title="doc.description"
          class="shrink-0 rounded-md border px-3 py-2 text-left transition"
          :class="
            selectedSlug === doc.slug
              ? 'border-amber-400/40 bg-amber-400/10 text-amber-100'
              : 'border-neutral-800 bg-neutral-900/40 text-neutral-300 hover:border-neutral-700 hover:bg-neutral-900'
          "
          type="button"
          @click="selectedSlug = doc.slug"
        >
          <span class="inline-flex items-center gap-2 whitespace-nowrap text-sm font-semibold">
            <Icon :icon="doc.icon" class="size-4" aria-hidden="true" />
            {{ doc.title }}
          </span>
        </button>
      </nav>

      <article class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5 sm:p-7">
        <div class="admin-markdown" v-html="renderedContent" />
      </article>
    </div>
  </section>
</template>
