import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { test, expect } from "@playwright/test";
import {
  customerApi,
  customerAgreement,
  customerOrderId,
} from "./customer-api";
import { mockApi, agreement, orderId } from "./mock-api";

const pdf = await readFile(
  new URL("./fixtures/agreement.pdf", import.meta.url),
);
const sha256 = (bytes: Buffer) =>
  createHash("sha256").update(bytes).digest("hex");
const cases = [
  { kind: "initial", revision: 1, status: "awaiting_customer" },
  { kind: "returned", revision: 2, status: "under_review" },
  { kind: "final", revision: 3, status: "approved" },
] as const;
const labels = {
  customer: {
    initial: "Скачать соглашение исполнителя",
    returned: "Скачать отправленный PDF",
    final: "Скачать подписанное соглашение",
  },
  admin: {
    initial: "Скачать PDF исполнителя",
    returned: "Скачать PDF заказчика",
    final: "Скачать окончательный PDF",
  },
};

for (const role of ["customer", "admin"] as const) {
  for (const { kind, revision, status } of cases) {
    for (const width of [1440, 390]) {
      test(`${role} downloads ${kind} PDF unchanged without a viewer at ${width}px`, async ({
        page,
        context,
      }) => {
        await page.setViewportSize({ width, height: 900 });
        if (role === "customer") {
          const state = await customerApi(page);
          state.agreement = customerAgreement(status, revision);
        } else {
          const state = await mockApi(page);
          state.agreement = agreement(status, revision);
        }
        const id = role === "customer" ? customerOrderId : orderId;
        let requests = 0;
        await page.route(
          `**/api/${role}/orders/${id}/agreement/${kind}`,
          (route) => {
            requests++;
            return route.fulfill({
              contentType: "application/pdf",
              headers: {
                "Content-Disposition": `attachment; filename="agreement-217-${kind}.pdf"`,
                "X-Agreement-Revision": String(revision),
                ETag: `"${sha256(pdf)}"`,
              },
              body: pdf,
            });
          },
        );
        await page.goto(`/${role}/orders/${id}`);
        const url = page.url();
        const openedPages: string[] = [];
        context.on("page", (opened) => openedPages.push(opened.url()));
        const button = page.getByRole("button", {
          name: labels[role][kind],
          exact: true,
        });
        await expect(button).toBeVisible();
        await button.focus();
        await expect(button).toBeFocused();
        const pending = page.waitForEvent("download");
        await page.keyboard.press("Enter");
        const downloaded = await pending;
        expect(downloaded.suggestedFilename()).toBe(
          `order-217-${kind}-v${revision}.pdf`,
        );
        expect(await downloaded.failure()).toBeNull();
        const bytes = await readFile((await downloaded.path())!);
        expect(bytes).toEqual(pdf);
        expect(sha256(bytes)).toBe(sha256(pdf));
        await expect(button).toBeEnabled();
        expect(requests).toBe(1);
        await expect(page).toHaveURL(url);
        expect(openedPages).toEqual([]);
        expect(context.pages()).toEqual([page]);
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= window.innerWidth,
          ),
        ).toBe(true);
      });
    }
  }

  for (const status of [401, 403, 404, 503]) {
    test(`${role} does not save an error response (${status}) as PDF`, async ({
      page,
      context,
    }) => {
      const state =
        role === "customer" ? await customerApi(page) : await mockApi(page);
      state.agreement =
        role === "customer"
          ? customerAgreement("approved", 3)
          : agreement("approved", 3);
      const id = role === "customer" ? customerOrderId : orderId;
      let requests = 0;
      await page.route(
        `**/api/${role}/orders/${id}/agreement/final`,
        (route) => {
          requests++;
          if (status === 401) state.authenticated = false;
          return route.fulfill({
            status,
            json: { detail: "Download unavailable" },
          });
        },
      );
      await page.goto(`/${role}/orders/${id}`);
      const downloads: string[] = [];
      page.on("download", (download) =>
        downloads.push(download.suggestedFilename()),
      );
      await page
        .getByRole("button", { name: labels[role].final, exact: true })
        .click();
      if (status === 401) {
        await expect(page).toHaveURL(
          role === "customer" ? "/auth/login" : "/auth/admin",
        );
        await expect(
          page.getByRole("heading", {
            name:
              role === "customer" ? "Войти по ссылке" : "Вход администратора",
            exact: true,
          }),
        ).toBeVisible();
      } else {
        await expect(page.getByRole("alert")).toBeVisible();
        await expect(
          page.getByRole("button", { name: labels[role].final, exact: true }),
        ).toBeEnabled();
        await expect(page).toHaveURL(`/${role}/orders/${id}`);
      }
      expect(requests).toBe(1);
      expect(downloads).toEqual([]);
      expect(context.pages()).toEqual([page]);
    });
  }
}
