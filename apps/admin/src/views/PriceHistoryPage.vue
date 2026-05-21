<template>
  <section class="space-y-6">
    <div>
      <p class="text-sm font-medium text-amber-300">Price history</p>
      <h2 class="mt-2 text-2xl font-semibold text-white">Product observations over time</h2>
      <p class="mt-2 max-w-3xl text-sm leading-6 text-neutral-400">
        Select a source product from the catalog to inspect repeated price observations and scrape timestamps.
      </p>
    </div>

    <div class="rounded-lg border border-neutral-800 bg-neutral-900/40 p-8 text-sm text-neutral-500">
      The first detail view will consume <code class="text-neutral-300">GET /products/:id/prices</code>.
    </div>
  </section>
</template>
