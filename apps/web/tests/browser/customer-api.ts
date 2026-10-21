import type { Page } from "@playwright/test";
import type { Models } from "../../app/lib/customer/api";
export const customerOrderId = "00000000-0000-0000-0000-000000000101";
export const customerPrincipalId = "00000000-0000-0000-0000-000000000102";
export const now = "2026-10-21T10:00:00Z";
export function customerAgreement(
  status: Models["AgreementStatus"] = "awaiting_customer",
  revision = 1,
): Models["AgreementRead"] {
  return {
    id: customerPrincipalId,
    order_id: customerOrderId,
    status,
    revision,
    initial_available: status !== "approved",
    returned_available: status === "under_review",
    final_available: status === "approved",
    final_sha256: status === "approved" ? "a".repeat(64) : null,
    rejection_reason:
      status === "rejected" ? "Подпишите вторую страницу" : null,
    verified_at: status === "approved" ? now : null,
    verified_by_id: null,
  };
}
export function customerDeletion(): Models["CustomerDeletionRead"] {
  return {
    id: customerPrincipalId,
    order_id: customerOrderId,
    reason: "retention_expired",
    status: "waiting",
    due_at: now,
    early_authorized_at: null,
    deferred_until: null,
    performed_at: null,
  };
}
export async function customerApi(page: Page) {
  const state = {
    authenticated: true,
    role: "customer",
    empty: false,
    requestStatus: 202,
    verifyStatus: 204,
    uploadStatus: 200,
    materialsStatus: 200,
    permissionStatus: 200,
    csrfStatus: 200,
    verifyGate: null as Promise<void> | null,
    calls: [] as {
      method: string;
      path: string;
      body: Record<string, unknown> | null;
      csrf?: string;
      revision?: string;
      bytes: Buffer | null;
      contentType?: string;
    }[],
    order: {
      id: customerOrderId,
      number: 217,
      customer_id: customerPrincipalId,
      service_type: "analysis",
      description: "Согласованный анализ документов",
      agreed_price: "1250.50",
      status: "awaiting_agreement",
      created_at: now,
      ready_at: null,
      result_notified_at: null,
      closed_at: null,
    } as Models["OrderRead"],
    agreement: customerAgreement() as Models["AgreementRead"] | null,
    folder: null as Models["CustomerFolderRead"] | null,
    materials: null as Models["HandoverRead"] | null,
    deletion: null as Models["CustomerDeletionRead"] | null,
  };
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      const request = route.request(),
        path = new URL(request.url()).pathname,
        method = request.method(),
        headers = request.headers();
      const body = headers["content-type"]?.includes("application/json")
        ? (request.postDataJSON() as Record<string, unknown>)
        : null;
      state.calls.push({
        method,
        path,
        body,
        csrf: headers["x-csrf-token"],
        revision: headers["x-agreement-revision"],
        bytes: request.postDataBuffer(),
        contentType: headers["content-type"],
      });
      const send = (json: unknown, status = 200) =>
        route.fulfill({ status, json });
      if (path === "/api/auth/csrf")
        return send({ csrf_token: "customer-csrf" }, state.csrfStatus);
      if (path === "/api/auth/magic-link/request")
        return send({}, state.requestStatus);
      if (path === "/api/auth/magic-link/verify") {
        if (state.verifyGate) await state.verifyGate;
        if (state.verifyStatus !== 204) return send({}, state.verifyStatus);
        state.authenticated = true;
        state.role = "customer";
        return route.fulfill({ status: 204 });
      }
      if (path === "/api/auth/session")
        return state.authenticated
          ? send({
              id: customerPrincipalId,
              role: state.role,
              email: "client@example.test",
              expires_at: "2030-01-01T00:00:00Z",
            })
          : send({}, 401);
      if (path === "/api/auth/logout") {
        state.authenticated = false;
        return route.fulfill({ status: 204 });
      }
      if (!state.authenticated) return send({}, 401);
      if (state.role !== "customer") return send({}, 403);
      if (path === "/api/customer/orders")
        return send(state.empty ? [] : [state.order]);
      const base = `/api/customer/orders/${customerOrderId}`;
      if (path !== base && !path.startsWith(base + "/")) return send({}, 404);
      if (path === base) return send(state.order);
      if (path === base + "/agreement")
        return state.agreement ? send(state.agreement) : send({}, 404);
      if (
        method === "GET" &&
        /\/agreement\/(initial|returned|final)$/.test(path)
      )
        return route.fulfill({
          status: 200,
          contentType: "application/pdf",
          headers: {
            "X-Agreement-Revision": String(state.agreement?.revision ?? 1),
          },
          body: "%PDF-1.7\nsynthetic-customer-document\n%%EOF",
        });
      if (path === base + "/agreement/returned") {
        if (state.uploadStatus !== 200) {
          if (state.uploadStatus === 409)
            state.agreement = customerAgreement("awaiting_customer", 2);
          return send({}, state.uploadStatus);
        }
        state.agreement = customerAgreement(
          "under_review",
          (state.agreement?.revision ?? 0) + 1,
        );
        return send(state.agreement);
      }
      if (path === base + "/folder")
        return state.folder ? send(state.folder) : send({}, 404);
      if (path === base + "/materials") {
        if (method === "POST") {
          if (state.materialsStatus !== 200)
            return send({}, state.materialsStatus);
          state.materials ??= {
            submitted_at: now,
            note: body?.note as string | null,
          };
        }
        return send(state.materials);
      }
      if (path === base + "/deletion-request") return send(state.deletion);
      if (path === base + "/deletion-permission") {
        if (state.permissionStatus !== 200)
          return send({}, state.permissionStatus);
        state.deletion ??= customerDeletion();
        state.deletion.reason = "early_permission";
        state.deletion.early_authorized_at = now;
        return send(state.deletion);
      }
      return send({}, 404);
    },
  );
  return state;
}
