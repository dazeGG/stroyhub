<script setup lang="ts">
import { Icon } from '@iconify/vue'
import MarkdownIt from 'markdown-it'
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { icons } from '../lib/icons'

type HelpDoc = {
  slug: string
  title: string
  description: string
  icon: (typeof icons)[keyof typeof icons]
  group: string
}

const docs: HelpDoc[] = [
  {
    slug: 'overview',
    title: 'Обзор',
    description: 'Карта админки, роли разделов и общий операторский цикл.',
    icon: icons.files,
    group: 'Обзор',
  },
  {
    slug: 'dashboard',
    title: 'Качество каталога',
    description: 'Главная рабочая сводка по очередям, источникам и блокерам.',
    icon: icons.layoutDashboard,
    group: 'Работа',
  },
  {
    slug: 'workflow-queues',
    title: 'Рабочие очереди',
    description: 'Можно принять, проверка, похожие товары и проблемы данных.',
    icon: icons.listCheck,
    group: 'Работа',
  },
  {
    slug: 'canonical-products',
    title: 'Нормализованный каталог',
    description: 'Canonical products, офферы, кандидаты и переходы в детали.',
    icon: icons.tags,
    group: 'Каталог',
  },
  {
    slug: 'source-products',
    title: 'Исходные товары',
    description: 'Source products, фильтры, категории, цены и карточки источников.',
    icon: icons.package,
    group: 'Каталог',
  },
  {
    slug: 'product-detail',
    title: 'Карточка товара',
    description: 'Паспорт source product, ручная категория и история цен.',
    icon: icons.history,
    group: 'Каталог',
  },
  {
    slug: 'category-quality',
    title: 'Категоризация',
    description: 'Покрытие категориями, unmatched группы и отчет для issue.',
    icon: icons.category,
    group: 'Каталог',
  },
  {
    slug: 'shops',
    title: 'Источники товаров',
    description: 'Canonical магазины, source shops, связи и scrape metadata.',
    icon: icons.buildingStore,
    group: 'Источники',
  },
  {
    slug: 'shop-candidates',
    title: 'Новые источники',
    description: 'Подтверждение найденных 2GIS магазинов и стратегий поиска.',
    icon: icons.databaseImport,
    group: 'Источники',
  },
  {
    slug: 'scrapes',
    title: 'Загрузки',
    description: 'Скрейпы, здоровье источников, магазины, recent runs и pipeline status.',
    icon: icons.activity,
    group: 'Источники',
  },
  {
    slug: 'category-directory',
    title: 'Категории',
    description: 'Дерево нормализованных категорий и связь с quality review.',
    icon: icons.category,
    group: 'Техническое',
  },
  {
    slug: 'normalization-inbox',
    title: 'Очередь нормализации',
    description: 'Legacy inbox для source products и ручного принятия решений.',
    icon: icons.listCheck,
    group: 'Техническое',
  },
  {
    slug: 'match-review',
    title: 'Сверка связей',
    description: 'Read-only проверка candidate pairs и причин матчинга.',
    icon: icons.gitCompare,
    group: 'Техническое',
  },
]

const groupOrder = ['Обзор', 'Работа', 'Каталог', 'Источники', 'Техническое']

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
const searchQuery = ref('')

const selectedDoc = computed(() => {
  return docs.find((doc) => doc.slug === selectedSlug.value) || docs[0]
})

function getDocMarkdown(slug: string): string {
  return markdownFiles[`../help/${slug}.md`] || ''
}

const renderedContent = computed(() => {
  return markdown.render(getDocMarkdown(selectedDoc.value.slug))
})

const filteredGroups = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()

  return groupOrder
    .map((group) => {
      const items = docs.filter((doc) => {
        if (doc.group !== group) {
          return false
        }

        if (!query) {
          return true
        }

        const searchableText = `${doc.title} ${doc.description} ${doc.group} ${getDocMarkdown(doc.slug)}`.toLowerCase()
        return searchableText.includes(query)
      })

      return { group, items }
    })
    .filter((group) => group.items.length > 0)
})

function selectDoc(slug: string): void {
  selectedSlug.value = slug
}
</script>

<template>
  <section class="min-h-screen bg-admin-bg px-4 py-5 text-admin-text sm:px-6 lg:px-8">
    <div class="mx-auto max-w-7xl space-y-7">
      <header class="flex flex-col gap-5 border-b border-admin-border pb-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p class="inline-flex items-center gap-2 text-sm font-medium text-admin-link">
            <Icon :icon="icons.helpCircle" class="size-4" aria-hidden="true" />
            Помощь
          </p>
          <h2 class="mt-2 text-2xl font-semibold text-admin-text">Документация по админке</h2>
          <p class="mt-2 max-w-3xl text-sm leading-6 text-admin-text-muted">
            Визуальный справочник по разделам, рабочим сценариям и решениям оператора.
          </p>
        </div>

        <RouterLink
          to="/"
          class="inline-flex w-fit items-center rounded-md border border-admin-border-strong bg-admin-surface-muted px-3 py-2 text-sm font-medium text-admin-text transition hover:border-admin-border-strong hover:text-admin-link-hover"
        >
          <Icon :icon="icons.arrowLeft" class="mr-2 size-4" aria-hidden="true" />
          Назад в админку
        </RouterLink>
      </header>

      <div class="grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
        <aside class="h-fit rounded-lg border border-admin-border bg-admin-surface p-4 lg:sticky lg:top-5">
          <label class="relative block">
            <Icon :icon="icons.search" class="pointer-events-none absolute left-3 top-3 size-4 text-admin-text-faint" aria-hidden="true" />
            <input
              v-model="searchQuery"
              type="search"
              class="h-10 w-full rounded-md border border-admin-border bg-admin-surface pl-9 pr-3 text-sm text-admin-text outline-none transition placeholder:text-admin-text-faint focus:border-admin-focus"
              placeholder="Поиск по help"
              aria-label="Поиск по документации"
            >
          </label>

          <nav class="mt-5 space-y-5" aria-label="Разделы документации">
            <section v-for="group in filteredGroups" :key="group.group">
              <p class="px-2 text-xs font-semibold uppercase tracking-wide text-admin-text-faint">
                {{ group.group }}
              </p>
              <div class="mt-2 grid gap-1">
                <button
                  v-for="doc in group.items"
                  :key="doc.slug"
                  :title="doc.description"
                  class="rounded-md px-2 py-2 text-left transition"
                  :class="
                    selectedSlug === doc.slug
                      ? 'bg-admin-active text-admin-primary-text'
                      : 'text-admin-text-muted hover:bg-admin-surface-muted hover:text-admin-text'
                  "
                  type="button"
                  @click="selectDoc(doc.slug)"
                >
                  <span class="flex items-center gap-2 text-sm font-semibold">
                    <Icon :icon="doc.icon" class="size-4 shrink-0 text-current opacity-80" aria-hidden="true" />
                    {{ doc.title }}
                  </span>
                  <span class="mt-1 block text-xs leading-5 opacity-75">
                    {{ doc.description }}
                  </span>
                </button>
              </div>
            </section>
          </nav>

          <p
            v-if="filteredGroups.length === 0"
            class="mt-5 rounded-md border border-admin-border bg-admin-surface-muted px-3 py-4 text-sm leading-6 text-admin-text-muted"
          >
            Ничего не найдено. Попробуй другой запрос по названию раздела, сценарию или блоку на скриншоте.
          </p>
        </aside>

        <article class="min-w-0 rounded-lg border border-admin-border bg-admin-surface p-5 sm:p-7">
          <div class="mb-6 border-b border-admin-border pb-5">
            <p class="text-xs font-semibold uppercase tracking-wide text-admin-text-faint">
              {{ selectedDoc.group }}
            </p>
            <h3 class="mt-2 text-xl font-semibold text-admin-text">{{ selectedDoc.title }}</h3>
            <p class="mt-2 max-w-3xl text-sm leading-6 text-admin-text-muted">
              {{ selectedDoc.description }}
            </p>
          </div>
          <div class="admin-markdown" v-html="renderedContent" />
        </article>
      </div>
    </div>
  </section>
</template>
