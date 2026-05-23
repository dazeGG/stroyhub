import { createRouter, createWebHistory } from 'vue-router'

import CatalogPage from './views/CatalogPage.vue'
import CategoryDirectoryPage from './views/CategoryDirectoryPage.vue'
import CategoryReviewPage from './views/CategoryReviewPage.vue'
import DashboardPage from './views/DashboardPage.vue'
import HelpPage from './views/HelpPage.vue'
import MatchReviewPage from './views/MatchReviewPage.vue'
import ProductDetailPage from './views/ProductDetailPage.vue'
import ScrapeStatusPage from './views/ScrapeStatusPage.vue'
import ShopCandidateReviewPage from './views/ShopCandidateReviewPage.vue'
import ShopSourceManagementPage from './views/ShopSourceManagementPage.vue'

export const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) {
      return savedPosition
    }

    if (to.path === '/products' && from.path === '/products') {
      return false
    }

    return { top: 0 }
  },
  routes: [
    { path: '/', name: 'dashboard', component: DashboardPage },
    { path: '/products', name: 'source-products', component: CatalogPage },
    { path: '/shops', name: 'shops', component: ShopSourceManagementPage },
    { path: '/shops/candidates', name: 'shop-candidates', component: ShopCandidateReviewPage },
    { path: '/products/:productId', name: 'product-detail', component: ProductDetailPage },
    { path: '/scrapes', name: 'scrapes', component: ScrapeStatusPage },
    { path: '/categories', name: 'categories', component: CategoryDirectoryPage },
    { path: '/categories/quality', name: 'category-quality', component: CategoryReviewPage },
    { path: '/matches', name: 'matches', component: MatchReviewPage },
    { path: '/help', name: 'help', component: HelpPage, meta: { fullPage: true } },
  ],
})
