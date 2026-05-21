<template>
  <section class="space-y-6">
    <div>
      <p class="text-sm font-medium text-amber-300">Статус скрейпов</p>
      <h2 class="mt-2 text-2xl font-semibold text-white">Здоровье источников</h2>
      <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
        Смотрим последние запуски, упавшие магазины, устаревшие источники и расписание следующих запусков.
      </p>
    </div>

    <div class="grid gap-4 md:grid-cols-3">
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="text-sm text-neutral-500">Успешные запуски</p>
        <p class="mt-3 text-3xl font-semibold text-white">-</p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="text-sm text-neutral-500">Ошибки</p>
        <p class="mt-3 text-3xl font-semibold text-white">-</p>
      </div>
      <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5">
        <p class="text-sm text-neutral-500">Магазины</p>
        <p class="mt-3 text-3xl font-semibold text-white">-</p>
      </div>
    </div>
  </section>
</template>
