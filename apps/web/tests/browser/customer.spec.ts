import { test, expect } from "@playwright/test";
import {
  customerApi,
  customerAgreement,
  customerDeletion,
  customerOrderId,
  now,
} from "./customer-api";

test("anonymous customer visits login, requests a link with CSRF, and sees no account disclosure", async ({
  page,
}) => {
  const state = await customerApi(page);
  state.authenticated = false;
  await page.goto("/customer/orders");
  await expect(
    page.getByRole("heading", { name: "Войти по ссылке", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Ваш email").fill("client@example.test");
  await page
    .getByRole("button", { name: "Получить ссылку для входа", exact: true })
    .click();
  const feedback = page
    .getByRole("status")
    .filter({ hasText: "Если для этого email открыт доступ" });
  await expect(feedback).toBeVisible();
  const first = await feedback.textContent();
  await page.getByLabel("Ваш email").fill("unknown@example.test");
  await page
    .getByRole("button", { name: "Запросить новую ссылку", exact: true })
    .click();
  await expect(feedback).toHaveText(first!);
  const calls = state.calls.filter((call) =>
    call.path.endsWith("/magic-link/request"),
  );
  expect(calls.map((call) => call.body)).toEqual([
    { email: "client@example.test" },
    { email: "unknown@example.test" },
  ]);
  expect(calls.every((call) => call.csrf === "customer-csrf")).toBe(true);
  expect(page.url()).not.toContain("email");
});

test("email link token is removed from URL and is consumed only on explicit confirmation", async ({
  page,
}) => {
  const state = await customerApi(page);
  state.authenticated = false;
  const token = "a".repeat(43),
    requests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "GET") requests.push(request.url());
  });
  await page.goto(`/auth/magic-link#token=${token}`);
  await expect(
    page.getByRole("button", { name: "Подтвердить вход", exact: true }),
  ).toBeEnabled();
  await expect(page).toHaveURL(/\/auth\/magic-link$/);
  expect(state.calls.some((call) => call.path.endsWith("/verify"))).toBe(false);
  expect(await page.content()).not.toContain(token);
  expect(requests.some((url) => url.includes(token))).toBe(false);
  await page
    .getByRole("button", { name: "Подтвердить вход", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Мои заказы", exact: true }),
  ).toBeVisible();
  const verify = state.calls.find((call) => call.path.endsWith("/verify"))!;
  expect(verify.body).toEqual({ token });
  expect(verify.csrf).toBe("customer-csrf");
});

test("skip-to-content preserves the magic link until explicit confirmation", async ({
  page,
}) => {
  const state = await customerApi(page);
  state.authenticated = false;
  const token = "a".repeat(43);
  await page.goto(`/auth/magic-link#token=${token}`);
  const confirm = page.getByRole("button", {
    name: "Подтвердить вход",
    exact: true,
  });
  await expect(confirm).toBeEnabled();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "Перейти к содержимому" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/auth\/magic-link#main$/);
  await expect(confirm).toBeEnabled();
  expect(state.calls.some((call) => call.path.endsWith("/verify"))).toBe(false);
  await confirm.click();
  await expect(
    page.getByRole("heading", { name: "Мои заказы", exact: true }),
  ).toBeVisible();
  expect(
    state.calls
      .filter((call) => call.path.endsWith("/verify"))
      .map((call) => call.body),
  ).toEqual([{ token }]);
});

test("skip-to-content preserves the result of a pending magic-link verification", async ({
  page,
}) => {
  const state = await customerApi(page);
  state.authenticated = false;
  let release!: () => void;
  state.verifyGate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.goto(`/auth/magic-link#token=${"a".repeat(43)}`);
  await page
    .getByRole("button", { name: "Подтвердить вход", exact: true })
    .click();
  await expect
    .poll(
      () => state.calls.filter((call) => call.path.endsWith("/verify")).length,
    )
    .toBe(1);
  await page.getByRole("link", { name: "Перейти к содержимому" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/auth\/magic-link#main$/);
  state.verifyGate = null;
  release();
  await expect(page).toHaveURL(/\/customer\/orders$/);
  await expect(
    page.getByRole("heading", { name: "Мои заказы", exact: true }),
  ).toBeVisible();
  expect(
    state.calls.filter((call) => call.path.endsWith("/verify")),
  ).toHaveLength(1);
});

test("invalid and already used links provide a fresh-link path without automatic retries", async ({
  page,
}) => {
  const state = await customerApi(page);
  state.verifyStatus = 401;
  await page.goto("/auth/magic-link#token=invalid");
  await expect(
    page.getByRole("button", { name: "Подтвердить вход", exact: true }),
  ).toBeDisabled();
  await expect(page).toHaveURL(/\/auth\/magic-link$/);
  expect(state.calls.some((call) => call.path.endsWith("/verify"))).toBe(false);
  await page.goto(`/auth/magic-link#token=${"b".repeat(43)}`);
  await page
    .getByRole("button", { name: "Подтвердить вход", exact: true })
    .click();
  await expect(
    page.getByText("Ссылка истекла или уже использована.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Подтвердить вход", exact: true }),
  ).toBeDisabled();
  expect(
    state.calls.filter((call) => call.path.endsWith("/verify")),
  ).toHaveLength(1);
  await page
    .getByRole("link", { name: "Получить новую ссылку", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Войти по ссылке", exact: true }),
  ).toBeVisible();
});

test("a new fragment on the same page replaces the in-memory login token", async ({
  page,
}) => {
  const state = await customerApi(page);
  await page.goto(`/auth/magic-link#token=${"a".repeat(43)}`);
  await expect(page).toHaveURL(/\/auth\/magic-link$/);
  await page.evaluate((token) => {
    window.location.hash = `token=${token}`;
  }, "b".repeat(43));
  await expect(page).toHaveURL(/\/auth\/magic-link$/);
  await page
    .getByRole("button", { name: "Подтвердить вход", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Мои заказы", exact: true }),
  ).toBeVisible();
  expect(
    state.calls.find((call) => call.path.endsWith("/verify"))!.body,
  ).toEqual({ token: "b".repeat(43) });
});

test("a pending login cannot silently consume a newly opened link", async ({
  page,
}) => {
  const state = await customerApi(page);
  state.authenticated = false;
  let release!: () => void;
  state.verifyGate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.goto(`/auth/magic-link#token=${"a".repeat(43)}`);
  await page
    .getByRole("button", { name: "Подтвердить вход", exact: true })
    .click();
  await expect
    .poll(
      () => state.calls.filter((call) => call.path.endsWith("/verify")).length,
    )
    .toBe(1);
  await page.evaluate((token) => {
    window.location.hash = `token=${token}`;
  }, "b".repeat(43));
  await expect(page).toHaveURL(/\/auth\/magic-link$/);
  state.verifyGate = null;
  release();
  await expect(
    page.getByRole("button", { name: "Подтвердить вход", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Подтвердить вход", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Мои заказы", exact: true }),
  ).toBeVisible();
  expect(
    state.calls
      .filter((call) => call.path.endsWith("/verify"))
      .map((call) => call.body),
  ).toEqual([{ token: "a".repeat(43) }, { token: "b".repeat(43) }]);
});

test("request rate limiting and failed CSRF show errors without consuming a link", async ({
  page,
}) => {
  const state = await customerApi(page);
  state.requestStatus = 429;
  await page.goto("/auth/login");
  await page.getByLabel("Ваш email").fill("client@example.test");
  await page
    .getByRole("button", { name: "Получить ссылку для входа", exact: true })
    .click();
  await expect(
    page.getByText("Слишком много запросов. Повторите позже.", { exact: true }),
  ).toBeVisible();
  state.csrfStatus = 503;
  await page.goto(`/auth/magic-link#token=${"c".repeat(43)}`);
  await page
    .getByRole("button", { name: "Подтвердить вход", exact: true })
    .click();
  await expect(page.getByRole("alert")).toBeVisible();
  expect(state.calls.some((call) => call.path.endsWith("/verify"))).toBe(false);
});

test("customer orders have the email-compatible address and support logout", async ({
  page,
}) => {
  const state = await customerApi(page);
  await page.goto("/customer");
  await expect(page).toHaveURL(/\/customer\/orders$/);
  await page
    .getByRole("link", { name: "Открыть заказ № 217", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Заказ № 217", exact: true }),
  ).toBeVisible();
  expect(state.calls.some((call) => call.path.startsWith("/api/admin/"))).toBe(
    false,
  );
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Войти по ссылке", exact: true }),
  ).toBeVisible();
});

test("empty order list and administrator sessions do not expose customer records", async ({
  page,
}) => {
  const state = await customerApi(page);
  state.empty = true;
  await page.goto("/customer/orders");
  await expect(
    page.getByRole("heading", { name: "Заказов пока нет", exact: true }),
  ).toBeVisible();
  state.empty = false;
  state.role = "admin";
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Войти по ссылке", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Согласованный анализ документов", { exact: true }),
  ).toHaveCount(0);
});

test("foreign order and agreement paths disclose no order details or files", async ({
  page,
}) => {
  const state = await customerApi(page);
  await page.goto("/customer/orders/00000000-0000-0000-0000-000000000999");
  await expect(
    page.getByText("Заказ не найден или недоступен.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Согласованный анализ документов", { exact: true }),
  ).toHaveCount(0);
  expect(
    state.calls.some(
      (call) =>
        call.path.endsWith("/agreement") || call.path.endsWith("/folder"),
    ),
  ).toBe(false);
});

test("signed agreement upload sends original bytes, CSRF and a fixed revision", async ({
  page,
}) => {
  const state = await customerApi(page),
    bytes = Buffer.from([37, 80, 68, 70, 45, 49, 46, 55, 10, 0, 255, 128]);
  await page.goto(`/customer/orders/${customerOrderId}`);
  await page
    .getByLabel("Подписанное соглашение PDF", { exact: true })
    .setInputFiles({
      name: "signed.pdf",
      mimeType: "application/pdf",
      buffer: bytes,
    });
  await page.getByLabel("Отправляю соглашение с моей подписью").check();
  await page
    .getByRole("button", { name: "Отправить подписанный PDF", exact: true })
    .click();
  await expect(
    page.getByText("Подписанный PDF отправлен исполнителю на проверку.", {
      exact: true,
    }),
  ).toBeVisible();
  const call = state.calls.find(
    (call) =>
      call.method === "POST" && call.path.endsWith("/agreement/returned"),
  )!;
  expect(call.bytes).toEqual(bytes);
  expect(call.revision).toBe("1");
  expect(call.csrf).toBe("customer-csrf");
  expect(call.contentType).toBe("application/pdf");
  await expect(
    page.getByText("Ваш PDF получен и ожидает проверки исполнителем.", {
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByLabel("Подписанное соглашение PDF", { exact: true })
    .setInputFiles({
      name: "replacement.pdf",
      mimeType: "application/pdf",
      buffer: bytes,
    });
  await page.getByLabel("Отправляю соглашение с моей подписью").check();
  await page
    .getByRole("button", { name: "Заменить отправленный PDF", exact: true })
    .click();
  await expect.poll(() => state.agreement?.revision).toBe(3);
  expect(
    state.calls
      .filter(
        (call) =>
          call.method === "POST" && call.path.endsWith("/agreement/returned"),
      )
      .map((call) => call.revision),
  ).toEqual(["1", "2"]);
});

for (const status of [409, 413, 422]) {
  test(`failed signed PDF upload (${status}) is not retried or shown as successful`, async ({
    page,
  }) => {
    const state = await customerApi(page);
    state.uploadStatus = status;
    state.agreement = customerAgreement("rejected", 1);
    await page.goto(`/customer/orders/${customerOrderId}`);
    await expect(
      page.getByText(
        "Исполнитель отклонил документ: Подпишите вторую страницу",
        { exact: true },
      ),
    ).toBeVisible();
    await page
      .getByLabel("Подписанное соглашение PDF", { exact: true })
      .setInputFiles({
        name: "signed.pdf",
        mimeType: "application/pdf",
        buffer: Buffer.from("%PDF-synthetic"),
      });
    await page.getByLabel("Отправляю соглашение с моей подписью").check();
    await page
      .getByRole("button", { name: "Отправить подписанный PDF", exact: true })
      .click();
    await expect(
      page.getByRole("alert").filter({
        hasText:
          status === 409
            ? "Данные или условия"
            : status === 413
              ? "PDF превышает"
              : "Проверьте заполненные",
      }),
    ).toBeVisible();
    expect(
      state.calls.filter(
        (call) =>
          call.method === "POST" && call.path.endsWith("/agreement/returned"),
      ),
    ).toHaveLength(1);
    await expect(
      page.getByText("Подписанный PDF отправлен исполнителю на проверку.", {
        exact: true,
      }),
    ).toHaveCount(0);
    if (status === 409)
      await expect(
        page.getByLabel("Подписанное соглашение PDF", { exact: true }),
      ).toHaveValue("");
  });
}

test("completed orders retain final agreement download after material deletion", async ({
  page,
}) => {
  const state = await customerApi(page);
  state.order.status = "completed";
  state.order.result_notified_at = now;
  state.agreement = customerAgreement("approved", 3);
  state.deletion = customerDeletion();
  state.deletion.status = "performed";
  state.deletion.performed_at = now;
  await page.goto(`/customer/orders/${customerOrderId}`);
  const pending = page.waitForEvent("download");
  await page
    .getByRole("button", {
      name: "Скачать подписанное соглашение",
      exact: true,
    })
    .click();
  const downloaded = await pending;
  expect(downloaded.suggestedFilename()).toBe("order-217-final-v3.pdf");
  await expect(
    page.getByText("Материалы удалены, ссылка на папку больше недоступна.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Подписанное соглашение PDF", { exact: true }),
  ).toHaveCount(0);
  expect(
    state.calls.some((call) => call.path.endsWith("/agreement/final")),
  ).toBe(true);
});

test("handover requires a confirmation and remains visible after reload", async ({
  page,
}) => {
  const state = await customerApi(page);
  state.order.status = "awaiting_materials";
  state.agreement = customerAgreement("approved", 3);
  state.folder = { folder_url: "https://disk.yandex.ru/invite/synthetic" };
  await page.goto(`/customer/orders/${customerOrderId}`);
  await expect(
    page.getByRole("link", {
      name: "Открыть папку на Яндекс Диске",
      exact: false,
    }),
  ).toHaveAttribute("href", state.folder.folder_url);
  await page
    .getByRole("button", {
      name: "Подтвердить передачу материалов",
      exact: true,
    })
    .click();
  expect(
    state.calls.some(
      (call) => call.method === "POST" && call.path.endsWith("/materials"),
    ),
  ).toBe(false);
  await page
    .getByLabel("Примечание к передаче", { exact: false })
    .fill("Переданы тома 1–3");
  await page
    .getByLabel("Я завершил передачу материалов", { exact: false })
    .check();
  await page
    .getByRole("button", {
      name: "Подтвердить передачу материалов",
      exact: true,
    })
    .click();
  await expect(
    page.getByText("Передача материалов отмечена.", { exact: false }).first(),
  ).toBeVisible();
  await page.reload();
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "Передача материалов отмечена" }),
  ).toBeVisible();
  await expect(
    page.getByText("Переданы тома 1–3", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Подтвердить передачу материалов",
      exact: true,
    }),
  ).toHaveCount(0);
  const submitted = state.calls.filter(
    (call) => call.method === "POST" && call.path.endsWith("/materials"),
  );
  expect(submitted).toHaveLength(1);
  expect(submitted[0].body).toEqual({ note: "Переданы тома 1–3" });
});

test("only an explicit customer permission is sent, never an administrative delete", async ({
  page,
}) => {
  const state = await customerApi(page);
  state.order.status = "result_ready";
  state.order.result_notified_at = now;
  state.agreement = customerAgreement("approved", 3);
  await page.goto(`/customer/orders/${customerOrderId}`);
  await page
    .getByRole("button", { name: "Разрешить удаление материалов", exact: true })
    .click();
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  expect(
    state.calls.some((call) => call.path.endsWith("/deletion-permission")),
  ).toBe(false);
  await page
    .getByRole("button", { name: "Разрешить удаление материалов", exact: true })
    .click();
  await page.getByLabel("Разрешаю удалить материалы", { exact: false }).check();
  await page
    .getByRole("button", {
      name: "Подтвердить разрешение на удаление",
      exact: true,
    })
    .click();
  await expect(
    page.getByText(
      "Разрешение сохранено. Удаление отдельно подтверждает исполнитель.",
      { exact: true },
    ),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Ваше разрешение получено", { exact: false }),
  ).toBeVisible();
  expect(
    state.calls
      .filter(
        (call) =>
          call.method === "POST" && call.path.endsWith("/deletion-permission"),
      )
      .map((call) => call.body),
  ).toEqual([{ confirm: true }]);
  expect(
    state.calls.some(
      (call) =>
        call.path.startsWith("/api/admin/") ||
        call.path.endsWith("/folder/delete"),
    ),
  ).toBe(false);
  await expect(
    page.getByRole("button", {
      name: "Разрешить удаление материалов",
      exact: true,
    }),
  ).toHaveCount(0);
});

for (const status of [
  "awaiting_agreement",
  "awaiting_materials",
  "in_progress",
  "cancelled",
] as const) {
  test(`order ${status} cannot offer early deletion permission`, async ({
    page,
  }) => {
    const state = await customerApi(page);
    state.order.status = status;
    await page.goto(`/customer/orders/${customerOrderId}`);
    await expect(
      page.getByRole("heading", { name: "Заказ № 217", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", {
        name: "Разрешить удаление материалов",
        exact: true,
      }),
    ).toHaveCount(0);
  });
}

test("customer cannot change an administrator deletion decision or see its private note", async ({
  page,
}) => {
  const state = await customerApi(page);
  state.order.status = "completed";
  state.order.result_notified_at = now;
  state.agreement = customerAgreement("approved", 3);
  state.deletion = customerDeletion();
  state.deletion.status = "confirmed";
  await page.goto(`/customer/orders/${customerOrderId}`);
  await expect(
    page.getByText("Исполнитель подтвердил решение об удалении", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Разрешить удаление материалов",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(state.calls.some((call) => call.path.startsWith("/api/admin/"))).toBe(
    false,
  );
});

test("unsafe folder links are not exposed and customer pages contain no material uploads", async ({
  page,
}) => {
  const state = await customerApi(page);
  state.order.status = "awaiting_materials";
  state.agreement = customerAgreement("approved", 3);
  state.folder = { folder_url: "https://example.test/invite/unsafe" };
  await page.goto(`/customer/orders/${customerOrderId}`);
  await expect(
    page.getByRole("heading", { name: "Заказ № 217", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", {
      name: "Открыть папку на Яндекс Диске",
      exact: false,
    }),
  ).toHaveCount(0);
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
});

test("expired customer sessions return to customer login during an action", async ({
  page,
}) => {
  const state = await customerApi(page);
  await page.goto(`/customer/orders/${customerOrderId}`);
  await page
    .getByLabel("Подписанное соглашение PDF", { exact: true })
    .setInputFiles({
      name: "signed.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-test"),
    });
  await page.getByLabel("Отправляю соглашение с моей подписью").check();
  state.authenticated = false;
  await page
    .getByRole("button", { name: "Отправить подписанный PDF", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Войти по ссылке", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Согласованный анализ документов", { exact: true }),
  ).toHaveCount(0);
});

test("customer result screens are responsive and private SSR contains no customer data", async ({
  page,
}) => {
  const state = await customerApi(page);
  state.order.status = "result_ready";
  state.order.result_notified_at = now;
  state.agreement = customerAgreement("approved", 3);
  state.folder = {
    folder_url: "https://disk.yandex.ru/client/disk/SINEGOR/order-217",
  };
  const response = await page.request.get(
    `/customer/orders/${customerOrderId}`,
  );
  expect(response.headers()["cache-control"]).toBe("no-store");
  expect(response.headers()["referrer-policy"]).toBe("no-referrer");
  const html = await response.text();
  expect(html).toContain("Загрузка личного кабинета");
  expect(html).not.toContain("client@example.test");
  expect(html).not.toContain("Согласованный анализ документов");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/customer/orders/${customerOrderId}`);
  await expect(
    page.getByText("Результат предоставлен, уведомление отправлено", {
      exact: false,
    }),
  ).toBeVisible();
  await page.screenshot({
    path: "/tmp/sinegor-f3-order-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "/tmp/sinegor-f3-order-mobile.png",
    fullPage: true,
  });
});
