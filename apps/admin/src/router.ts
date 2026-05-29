import { createRouter, createWebHistory } from 'vue-router'

import CatalogPage from './views/CatalogPage.vue'
import CatalogWorkflowQueuePage from './views/CatalogWorkflowQueuePage.vue'
import CanonicalProductDetailPage from './views/CanonicalProductDetailPage.vue'
import CanonicalProductListPage from './views/CanonicalProductListPage.vue'
import CategoryDirectoryPage from './views/CategoryDirectoryPage.vue'
import CategoryReviewPage from './views/CategoryReviewPage.vue'
import DashboardPage from './views/DashboardPage.vue'
import HelpPage from './views/HelpPage.vue'
import MatchReviewPage from './views/MatchReviewPage.vue'
import PatronReviewPage from './views/PatronReviewPage.vue'
import ProductDetailPage from './views/ProductDetailPage.vue'
import ProductNormalizationInboxPage from './views/ProductNormalizationInboxPage.vue'
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
    {
      path: '/workflows/queues/:queue',
      name: 'catalog-workflow-queue',
      component: CatalogWorkflowQueuePage,
    },
    { path: '/products', name: 'source-products', component: CatalogPage },
    { path: '/patron-review', name: 'patron-review', component: PatronReviewPage },
    {
      path: '/canonical-products',
      name: 'canonical-products',
      component: CanonicalProductListPage,
    },
    {
      path: '/products/normalization',
      name: 'product-normalization',
      component: ProductNormalizationInboxPage,
    },
    {
      path: '/canonical-products/:canonicalProductId',
      name: 'canonical-product-detail',
      component: CanonicalProductDetailPage,
    },
    { path: '/shops', name: 'shops', component: ShopSourceManagementPage },
    { path: '/shops/candidates', name: 'shop-candidates', component: ShopCandidateReviewPage },
    { path: '/products/:productId', name: 'product-detail', component: ProductDetailPage },
    { path: '/sources', redirect: '/shops' },
    { path: '/scrapes', name: 'scrapes', component: ScrapeStatusPage },
    { path: '/categories', name: 'categories', component: CategoryDirectoryPage },
    { path: '/categories/quality', name: 'category-quality', component: CategoryReviewPage },
    { path: '/matches', name: 'matches', component: MatchReviewPage },
    { path: '/help', name: 'help', component: HelpPage, meta: { fullPage: true } },
  ],
})
