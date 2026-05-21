<script setup lang="ts">
import MarkdownIt from 'markdown-it'
import { computed, ref } from 'vue'

const docs = [
  {
    slug: 'overview',
    title: 'Обзор',
    description: 'Как устроена админка и когда заводить issue.',
  },
  {
    slug: 'catalog',
    title: 'Каталог',
    description: 'Проверка исходных карточек, категорий и последних цен.',
  },
  {
    slug: 'prices',
    title: 'История цен',
    description: 'Price snapshots, повторы и null-price наблюдения.',
  },
  {
    slug: 'scrapes',
    title: 'Скрейпы',
    description: 'Статусы магазинов, recent runs и ошибки источников.',
  },
  {
    slug: 'categories',
    title: 'Категории',
    description: 'Unmatched группы, representative titles и экспорт в issue.',
  },
  {
    slug: 'matches',
    title: 'Матчинг',
    description: 'Read-only кандидаты, confidence и reason tokens.',
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
  <section class="space-y-6">
    <div>
      <p class="text-sm font-medium text-amber-300">Помощь</p>
      <h2 class="mt-2 text-2xl font-semibold text-white">Документация по админке</h2>
      <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
        Markdown-разделы с примерами экранов, рабочими сценариями и правилами для follow-up issues.
      </p>
    </div>

    <div class="grid gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
      <aside class="space-y-2">
        <button
          v-for="doc in docs"
          :key="doc.slug"
          class="w-full rounded-lg border px-4 py-3 text-left transition"
          :class="
            selectedSlug === doc.slug
              ? 'border-amber-400/40 bg-amber-400/10 text-white'
              : 'border-neutral-800 bg-neutral-900/40 text-neutral-300 hover:border-neutral-700 hover:bg-neutral-900'
          "
          type="button"
          @click="selectedSlug = doc.slug"
        >
          <span class="block text-sm font-semibold">{{ doc.title }}</span>
          <span class="mt-1 block text-xs leading-5 text-neutral-500">{{ doc.description }}</span>
        </button>
      </aside>

      <article class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5 sm:p-7">
        <div class="admin-markdown" v-html="renderedContent" />
      </article>
    </div>
  </section>
</template>
