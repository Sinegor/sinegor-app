import {
  index,
  layout,
  route,
  type RouteConfig,
} from "@react-router/dev/routes";
export default [
  layout("layouts/public.tsx", [
    index("routes/public/home.tsx"),
    route("auth/magic-link", "routes/auth/magic-link.tsx"),
    route("auth/admin", "routes/auth/admin.tsx"),
  ]),
  route("customer", "layouts/customer.tsx", [
    index("routes/customer/home.tsx"),
  ]),
  route("admin", "layouts/admin.tsx", [
    index("routes/admin/home.tsx"),
    route("customers", "routes/admin/customers.tsx"),
    route("customers/new", "routes/admin/customer-new.tsx"),
    route("customers/:customerId", "routes/admin/customer.tsx"),
    route("orders", "routes/admin/orders.tsx"),
    route("orders/new", "routes/admin/order-new.tsx"),
    route("orders/:orderId", "routes/admin/order.tsx"),
  ]),
] satisfies RouteConfig;
