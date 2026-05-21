import { createRouter, createWebHistory } from 'vue-router'

import CatalogPage from './views/CatalogPage.vue'
import CategoryDirectoryPage from './views/CategoryDirectoryPage.vue'
import CategoryReviewPage from './views/CategoryReviewPage.vue'
import HelpPage from './views/HelpPage.vue'
import MatchReviewPage from './views/MatchReviewPage.vue'
import PriceHistoryPage from './views/PriceHistoryPage.vue'
import ScrapeStatusPage from './views/ScrapeStatusPage.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'catalog', component: CatalogPage },
    { path: '/prices', name: 'prices', component: PriceHistoryPage },
    { path: '/scrapes', name: 'scrapes', component: ScrapeStatusPage },
    { path: '/categories', name: 'categories', component: CategoryDirectoryPage },
    { path: '/categories/quality', name: 'category-quality', component: CategoryReviewPage },
    { path: '/matches', name: 'matches', component: MatchReviewPage },
    { path: '/help', name: 'help', component: HelpPage, meta: { fullPage: true } },
  ],
})
