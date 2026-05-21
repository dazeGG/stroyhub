<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
      <div>
        <p class="text-sm font-medium text-amber-300">Product catalog</p>
        <h2 class="mt-2 text-2xl font-semibold text-white">Source product inspection</h2>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
          Search scraped source cards, compare normalized categories, and check latest observed prices.
        </p>
      </div>

      <div class="grid gap-3 sm:grid-cols-3 xl:min-w-[640px]">
        <UInput placeholder="Search title" />
        <USelectMenu placeholder="Category" :items="[]" />
        <USelectMenu placeholder="Shop" :items="[]" />
      </div>
    </div>

    <div class="overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900/40">
      <div class="grid grid-cols-[minmax(260px,2fr)_1fr_1fr_140px_150px] border-b border-neutral-800 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neutral-500">
        <span>Product</span>
        <span>Shop</span>
        <span>Category</span>
        <span>Latest price</span>
        <span>Last seen</span>
      </div>
      <div class="px-4 py-14 text-center text-sm text-neutral-500">
        Catalog data will load from <code class="text-neutral-300">GET /products</code>.
      </div>
    </div>
  </section>
</template>
