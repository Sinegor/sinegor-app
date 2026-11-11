import {
  index,
  layout,
  route,
  type RouteConfig,
} from "@react-router/dev/routes";
export default [
  route("sitemap.xml", "routes/resources/sitemap.ts", { caseSensitive: true }),
  route("robots.txt", "routes/resources/robots.ts", { caseSensitive: true }),
  layout("layouts/public.tsx", [
    index("routes/public/home.tsx"),
    route("services/ai-analysis", "routes/public/analysis.tsx", {
      caseSensitive: true,
    }),
    route("services/technical", "routes/public/technical.tsx", {
      caseSensitive: true,
    }),
    route("pages/:slug", "routes/public/page.tsx"),
    route("services/:slug", "routes/public/service.tsx"),
    route("about", "routes/public/about.tsx"),
    route("publications", "routes/public/publications.tsx"),
    route("publications/:slug", "routes/public/publication.tsx"),
    route("contacts", "routes/public/contacts.tsx"),
    route("documents", "routes/public/documents.tsx"),
    route("documents/:slug", "routes/public/document.tsx"),
    route("auth/magic-link", "routes/auth/magic-link.tsx"),
    route("auth/admin", "routes/auth/admin.tsx"),
    route("auth/login", "routes/auth/login.tsx"),
  ]),
  route("customer", "layouts/customer.tsx", [
    index("routes/customer/index.tsx"),
    route("orders", "routes/customer/home.tsx"),
    route("orders/:orderId", "routes/customer/order.tsx"),
  ]),
  route("admin", "layouts/admin.tsx", [
    index("routes/admin/home.tsx"),
    route("security-events", "routes/admin/security-events.tsx"),
    route("destructions", "routes/admin/destructions.tsx"),
    route("consultations", "routes/admin/consultations.tsx"),
    route("customers", "routes/admin/customers.tsx"),
    route("customers/new", "routes/admin/customer-new.tsx"),
    route("customers/:customerId", "routes/admin/customer.tsx"),
    route("orders", "routes/admin/orders.tsx"),
    route("orders/new", "routes/admin/order-new.tsx"),
    route("orders/:orderId", "routes/admin/order.tsx"),
  ]),
] satisfies RouteConfig;
