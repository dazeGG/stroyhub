<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
      <div>
        <p class="text-sm font-medium text-amber-300">Каталог товаров</p>
        <h2 class="mt-2 text-2xl font-semibold text-white">Инспекция исходных карточек</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
          Ищем собранные карточки, сверяем категории и смотрим последние наблюдения по ценам.
        </p>
      </div>

      <div class="grid gap-3 sm:grid-cols-3 xl:min-w-[640px]">
        <UInput placeholder="Поиск по названию" />
        <USelectMenu placeholder="Категория" :items="[]" />
        <USelectMenu placeholder="Магазин" :items="[]" />
      </div>
    </div>

    <div class="overflow-x-auto rounded-lg border border-neutral-800 bg-neutral-900/40">
      <div class="grid min-w-[840px] grid-cols-[minmax(260px,2fr)_1fr_1fr_140px_150px] border-b border-neutral-800 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neutral-500">
        <span>Товар</span>
        <span>Магазин</span>
        <span>Категория</span>
        <span>Цена</span>
        <span>Последний раз</span>
      </div>
      <div class="min-w-[840px] px-4 py-14 text-center text-sm text-neutral-500">
        Данные каталога будут загружаться из <code class="text-neutral-300">GET /products</code>.
      </div>
    </div>
  </section>
</template>
