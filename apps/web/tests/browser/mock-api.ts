import type { Page } from "@playwright/test";
import type { Models } from "../../app/lib/admin/api";
export const customerId = "00000000-0000-0000-0000-000000000001";
export const orderId = "00000000-0000-0000-0000-000000000002";
export const deletionId = "00000000-0000-0000-0000-000000000003";
const now = "2026-10-01T10:00:00Z";
export async function mockApi(page: Page) {
  const state = {
    authenticated: true,
    role: "admin",
    invitationFailure: false,
    csrfFailure: false,
    calls: [] as {
      method: string;
      path: string;
      body: Record<string, unknown> | null;
      csrf: string | undefined;
      revision: string | undefined;
      bytes: Buffer | null;
      contentType: string | undefined;
    }[],
    customers: [
      {
        id: customerId,
        email: "client@example.test",
        display_name: "Иван Петров",
        phone: "+7 900 111-22-33",
        blocked_at: null,
        block_reason: null,
        block_comment: null,
      },
    ] as Models["CustomerRead"][],
    order: {
      id: orderId,
      number: 217,
      customer_id: customerId,
      service_type: "analysis",
      description: "Согласованные условия",
      agreed_price: "1250.50",
      status: "awaiting_agreement",
      created_at: now,
      ready_at: null,
      result_notified_at: null,
      closed_at: null,
    } as Models["OrderRead"],
    agreement: null as Models["AgreementRead"] | null,
    folder: null as Models["FolderRead"] | null,
    deletion: null as Models["DeletionRead"] | null,
    payment: {
      status: "unpaid",
      confirmed_at: null,
      confirmed_by_id: null,
      note: null,
    } as Models["PaymentRead"],
    pdfRevision: 2,
    deleteCount: 0,
    approvalConflict: false,
    readinessFailure: false,
    mutationGate: null as Promise<void> | null,
  };
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      const request = route.request(),
        url = new URL(request.url()),
        method = request.method(),
        path = url.pathname;
      const headers = request.headers();
      let body = null;
      if (headers["content-type"]?.includes("application/json"))
        body = request.postDataJSON();
      state.calls.push({
        method,
        path,
        body,
        csrf: headers["x-csrf-token"],
        revision: headers["x-agreement-revision"],
        bytes: request.postDataBuffer(),
        contentType: headers["content-type"],
      });
      if (method !== "GET" && state.mutationGate) await state.mutationGate;
      const send = (
        json: unknown,
        status = 200,
        headers?: Record<string, string>,
      ) => route.fulfill({ status, json, headers });
      if (path === "/api/auth/csrf")
        return send(
          state.csrfFailure ? {} : { csrf_token: "test-csrf" },
          state.csrfFailure ? 503 : 200,
        );
      if (path === "/api/auth/admin/login") {
        state.authenticated = true;
        state.role = "admin";
        return route.fulfill({ status: 204 });
      }
      if (path === "/api/auth/session")
        return state.authenticated
          ? send({
              id: customerId,
              role: state.role,
              email: "admin@example.test",
              expires_at: "2030-01-01T00:00:00Z",
            })
          : send({}, 401);
      if (path === "/api/auth/logout") {
        state.authenticated = false;
        return route.fulfill({ status: 204 });
      }
      if (!state.authenticated) return send({}, 401);
      if (state.role !== "admin") return send({}, 403);
      if (path === "/api/admin/notifications/summary") return send([]);
      if (path === "/api/admin/customers" && method === "GET") {
        const q = (url.searchParams.get("q") ?? "").toLowerCase(),
          offset = Number(url.searchParams.get("offset") ?? 0),
          limit = Number(url.searchParams.get("limit") ?? 50);
        return send(
          state.customers
            .filter((c) =>
              [c.email, c.display_name, c.phone].some((v) =>
                v?.toLowerCase().includes(q),
              ),
            )
            .slice(offset, offset + limit),
        );
      }
      if (path === "/api/admin/customers" && method === "POST") {
        const customer = { ...state.customers[0], ...body };
        state.customers[0] = customer;
        return state.invitationFailure
          ? send({}, 503, { "X-Customer-ID": customer.id })
          : send(customer, 201);
      }
      if (path.endsWith("/invite")) {
        state.invitationFailure = false;
        return send({}, 202);
      }
      if (path === `/api/admin/customers/${customerId}`) {
        if (method === "PATCH") Object.assign(state.customers[0], body);
        return send(state.customers[0]);
      }
      if (path === "/api/admin/orders" && method === "GET")
        return send(
          url.searchParams.get("status") &&
            url.searchParams.get("status") !== state.order.status
            ? []
            : [state.order],
        );
      if (path === "/api/admin/orders" && method === "POST") {
        Object.assign(state.order, body);
        return send(state.order, 201);
      }
      if (path === `/api/admin/orders/${orderId}`) return send(state.order);
      if (path.endsWith("/terms")) {
        Object.assign(state.order, body);
        return send(state.order);
      }
      if (path.endsWith("/events"))
        return send([
          { id: deletionId, event_type: "order_created", created_at: now },
        ]);
      if (path.endsWith("/payment")) {
        if (method === "POST")
          Object.assign(state.payment, {
            status: "paid",
            confirmed_at: now,
            note: body?.note,
          });
        return send(state.payment);
      }
      if (path.endsWith("/materials")) return send(null);
      if (path.endsWith("/status")) {
        if (body?.status === "result_ready" && state.readinessFailure)
          return send({}, 503);
        Object.assign(state.order, { status: body?.status });
        return send(state.order);
      }
      if (path.endsWith("/agreement"))
        return state.agreement ? send(state.agreement) : send({}, 404);
      if (path.endsWith("/agreement/initial") && method === "POST") {
        state.agreement = agreement(
          "awaiting_customer",
          (state.agreement?.revision ?? 0) + 1,
        );
        return send(state.agreement);
      }
      if (
        /\/agreement\/(initial|returned|final)$/.test(path) &&
        method === "GET"
      )
        return route.fulfill({
          status: 200,
          contentType: "application/pdf",
          headers: { "X-Agreement-Revision": String(state.pdfRevision) },
          body: "%PDF-1.7\nsynthetic-pdf\n%%EOF",
        });
      if (
        path.endsWith("/agreement/approve") ||
        path.endsWith("/agreement/reject")
      ) {
        if (state.approvalConflict) {
          state.agreement = agreement("under_review", 3);
          return send({}, 409);
        }
        state.agreement = agreement(
          path.endsWith("approve") ? "approved" : "rejected",
          3,
        );
        if (state.agreement.status === "approved")
          state.order.status = "awaiting_materials";
        return send(state.agreement);
      }
      if (path.endsWith("/folder")) {
        if (method !== "GET") state.folder = folder();
        return state.folder ? send(state.folder) : send({}, 404);
      }
      if (path.endsWith("/folder/open"))
        return send({
          folder_url:
            "https://disk.yandex.ru/client/disk/SINEGOR/orders/order-217",
        });
      if (path.endsWith("/folder/link")) {
        state.folder!.folder_url = String(body?.folder_url);
        return send(state.folder);
      }
      if (path.endsWith("/deletion-request")) return send(state.deletion);
      if (path.endsWith("/deletion-request/confirm")) {
        state.deletion!.status = "confirmed";
        return send(state.deletion);
      }
      if (path.endsWith("/deletion-request/defer")) {
        Object.assign(state.deletion!, {
          status: "deferred",
          deferred_until: body?.deferred_until,
          admin_note: body?.note,
        });
        return send(state.deletion);
      }
      if (path.endsWith("/folder/delete")) {
        state.deleteCount++;
        state.folder!.deletion_started_at = now;
        state.folder!.deletion_operation_id = "operation-1";
        if (state.deleteCount > 1) {
          state.folder!.deleted_at = now;
          state.deletion!.status = "performed";
          state.deletion!.performed_at = now;
        }
        return send(state.folder, state.deleteCount === 1 ? 202 : 200);
      }
      return send({}, 404);
    },
  );
  return state;
}
export function agreement(
  status: Models["AgreementStatus"] = "under_review",
  revision = 2,
): Models["AgreementRead"] {
  return {
    id: deletionId,
    order_id: orderId,
    status,
    revision,
    initial_available: status !== "approved",
    returned_available: status === "under_review",
    final_available: status === "approved",
    final_sha256: null,
    rejection_reason: null,
    verified_at: null,
    verified_by_id: null,
  };
}
export function folder(): Models["FolderRead"] {
  return {
    id: deletionId,
    order_id: orderId,
    disk_path: "disk:/SINEGOR/orders/order-217",
    resource_id: "resource-217",
    folder_url: null,
    deleted_at: null,
    deletion_operation_id: null,
    deletion_started_at: null,
  };
}
export function deletion(): Models["DeletionRead"] {
  return {
    id: deletionId,
    order_id: orderId,
    reason: "retention_expired",
    status: "waiting",
    due_at: now,
    early_authorized_at: null,
    deferred_until: null,
    performed_at: null,
    created_at: now,
    confirmed_at: null,
    confirmed_by_id: null,
    admin_note: null,
  };
}
