import { test, expect } from "@playwright/test";
import {
  mockApi,
  agreement,
  folder,
  deletion,
  customerId,
  orderId,
  deletionId,
} from "./mock-api";

test("anonymous access requires separate admin login and supports logout", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.authenticated = false;
  await page.goto("/admin/customers");
  await expect(
    page.getByRole("heading", { name: "Вход администратора" }),
  ).toBeVisible();
  await page.getByLabel("Email администратора").fill("admin@example.test");
  await page.getByLabel("Пароль", { exact: true }).fill("test-password");
  await page.getByLabel("Одноразовый код").fill("123456");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Контакты и заказы" }),
  ).toBeVisible();
  const login = state.calls.find((c) => c.path.endsWith("/admin/login"))!;
  expect(login.csrf).toBe("test-csrf");
  expect(login.body).toEqual({
    email: "admin@example.test",
    password: "test-password",
    code: "123456",
  });
  await page.getByRole("button", { name: "Выйти" }).click();
  await expect(
    page.getByRole("heading", { name: "Вход администратора" }),
  ).toBeVisible();
});

test("customer role cannot view admin records", async ({ page }) => {
  const state = await mockApi(page);
  state.role = "customer";
  await page.goto("/admin/customers");
  await expect(page).toHaveURL("/customer/orders");
  await expect(page.getByText("Иван Петров", { exact: true })).toHaveCount(0);
});

test("search is sent to server and pagination preserves the query", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.customers = Array.from({ length: 26 }, (_, i) => ({
    id: `customer-${i}`,
    email: `match${i}@example.test`,
    display_name: `Заказчик ${i}`,
    phone: null,
  }));
  await page.goto("/admin/customers");
  await page.getByLabel("Поиск по имени, email или телефону").fill("match");
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(page).toHaveURL(/q=match/);
  await page.getByRole("link", { name: "Далее", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Заказчик 25", exact: true }),
  ).toBeVisible();
  await expect(page).toHaveURL(/offset=25/);
});

test("saved customer after SMTP failure opens existing card and retries invitation", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.invitationFailure = true;
  await page.goto("/admin/customers/new");
  await page.getByLabel("Email", { exact: true }).fill("new@example.test");
  await page.getByLabel("Имя или наименование").fill("Новый заказчик");
  await page.getByRole("button", { name: "Создать и пригласить" }).click();
  await expect(
    page.getByText("Заказчик создан, но приглашение не отправлено.", {
      exact: false,
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Повторить приглашение" }).click();
  await expect(
    page.getByText("Приглашение передано почтовому сервису."),
  ).toBeVisible();
  expect(
    state.calls.filter(
      (c) => c.method === "POST" && c.path === "/api/admin/customers",
    ),
  ).toHaveLength(1);
  expect(
    state.calls.some(
      (c) => c.path === `/api/admin/customers/${customerId}/invite`,
    ),
  ).toBe(true);
});

test("new order sends selected customer and decimal price as a string", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.goto(`/admin/orders/new?customer_id=${customerId}`);
  await page
    .getByRole("combobox", { name: "Услуга", exact: true })
    .selectOption("technical_preparation");
  await page.getByLabel("Согласованные условия").fill("Подготовка документов");
  await page
    .getByLabel("Согласованная стоимость", { exact: false })
    .fill("1250,50");
  await page
    .getByRole("button", { name: "Создать заказ", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Заказ № 217", exact: true }),
  ).toBeVisible();
  const call = state.calls.find(
    (c) => c.method === "POST" && c.path === "/api/admin/orders",
  )!;
  expect(call.body).toEqual({
    customer_id: customerId,
    service_type: "technical_preparation",
    description: "Подготовка документов",
    agreed_price: "1250.50",
  });
});

test("PDF upload sends raw bytes with current revision, not multipart or JSON", async ({
  page,
}) => {
  const state = await mockApi(page),
    bytes = Buffer.from("%PDF-1.7\nsynthetic-bytes\n%%EOF");
  await page.goto(`/admin/orders/${orderId}`);
  await page.getByLabel("PDF исполнителя", { exact: true }).setInputFiles({
    name: "agreement.pdf",
    mimeType: "application/pdf",
    buffer: bytes,
  });
  await page
    .getByRole("button", { name: "Загрузить PDF исполнителя", exact: true })
    .click();
  await expect(
    page.getByText("PDF исполнителя сохранён.", { exact: true }),
  ).toBeVisible();
  const call = state.calls.find(
    (c) => c.method === "POST" && c.path.endsWith("/agreement/initial"),
  )!;
  expect(call.revision).toBe("0");
  expect(call.contentType).toBe("application/pdf");
  expect(call.bytes).toEqual(bytes);
  expect(call.csrf).toBe("test-csrf");
});

test("agreement review uses downloaded revision and stale approval is not retried", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.agreement = agreement();
  state.approvalConflict = true;
  await page.goto(`/admin/orders/${orderId}`);
  await expect(
    page.getByRole("button", { name: "Продолжить", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Скачать PDF заказчика", exact: true })
    .click();
  await page
    .getByLabel("Я проверил документ и подписи", { exact: false })
    .check();
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await page
    .getByRole("button", { name: "Утвердить версию", exact: true })
    .click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(
    page.getByText("Данные или условия операции изменились.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Продолжить", exact: true }),
  ).toBeDisabled();
  const calls = state.calls.filter((c) =>
    c.path.endsWith("/agreement/approve"),
  );
  expect(calls).toHaveLength(1);
  expect(calls[0].body).toEqual({ revision: 2 });
});

test("payment and result readiness require explicit confirmations", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.order.status = "in_progress";
  state.agreement = agreement("approved", 3);
  state.folder = folder();
  await page.goto(`/admin/orders/${orderId}`);
  await page.getByLabel("Примечание к оплате").fill("Перевод получен");
  await page
    .getByRole("button", { name: "Подтвердить оплату", exact: true })
    .click();
  expect(
    state.calls.filter(
      (c) => c.method === "POST" && c.path.endsWith("/payment"),
    ),
  ).toHaveLength(0);
  await page
    .getByLabel("Я проверил поступление оплаты", { exact: false })
    .check();
  await page
    .getByRole("button", { name: "Подтвердить оплату", exact: true })
    .click();
  await expect(
    page.getByText("Оплата зафиксирована.", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Результат размещён в папке заказа").check();
  await page
    .getByLabel("Я вручную изменил права заказчика на просмотр")
    .check();
  await page
    .getByRole("button", { name: "Зафиксировать готовность", exact: true })
    .click();
  await expect(
    page.getByText("Результат готов, письмо принято почтовым сервисом.", {
      exact: true,
    }),
  ).toBeVisible();
  expect(
    state.calls.find((c) => c.method === "POST" && c.path.endsWith("/status"))!
      .body,
  ).toEqual({
    status: "result_ready",
    result_uploaded: true,
    access_read_only: true,
  });
});

test("SMTP readiness failure remains visible and does not claim result was delivered", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.order.status = "in_progress";
  state.readinessFailure = true;
  await page.goto(`/admin/orders/${orderId}`);
  await page.getByLabel("Результат размещён в папке заказа").check();
  await page
    .getByLabel("Я вручную изменил права заказчика на просмотр")
    .check();
  await page
    .getByRole("button", { name: "Зафиксировать готовность", exact: true })
    .click();
  await expect(
    page.getByText("При сбое SMTP уведомление остаётся в очереди", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(page.getByText("В работе", { exact: true })).toBeVisible();
});

test("deletion decision and actual deletion are separate; 202 needs explicit checking", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.order.status = "completed";
  state.deletion = deletion();
  state.folder = folder();
  await page.goto(`/admin/orders/${orderId}`);
  await page
    .getByRole("button", {
      name: "Подтвердить решение об удалении",
      exact: true,
    })
    .click();
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  expect(
    state.calls.filter(
      (c) => c.path.endsWith("/confirm") || c.path.endsWith("/delete"),
    ),
  ).toHaveLength(0);
  await page
    .getByRole("button", {
      name: "Подтвердить решение об удалении",
      exact: true,
    })
    .click();
  await page
    .getByLabel("Я проверил обращения заказчика", { exact: false })
    .check();
  await page
    .getByRole("button", { name: "Подтвердить решение", exact: true })
    .click();
  await expect(
    page.getByText(
      "Решение сохранено. Для удаления требуется отдельное действие.",
    ),
  ).toBeVisible();
  expect(state.deleteCount).toBe(0);
  await page
    .getByRole("button", { name: "Удалить папку окончательно", exact: true })
    .click();
  await page
    .getByLabel("Подтверждаю запуск или проверку", { exact: false })
    .check();
  await page
    .getByRole("button", { name: "Подтвердить операцию удаления", exact: true })
    .click();
  await expect(
    page.getByText("Операция уже начата.", { exact: false }),
  ).toBeVisible();
  expect(state.deleteCount).toBe(1);
  await expect(
    page.getByText("Удаление проверено", { exact: true }),
  ).toHaveCount(1); // label, not a success badge
  await page
    .getByRole("button", {
      name: "Проверить / повторить операцию удаления",
      exact: true,
    })
    .click();
  await page
    .getByLabel("Подтверждаю запуск или проверку", { exact: false })
    .check();
  await page
    .getByRole("button", { name: "Подтвердить операцию удаления", exact: true })
    .click();
  await expect(
    page.locator(".badge").filter({ hasText: "Удаление проверено" }),
  ).toBeVisible();
  expect(
    state.calls
      .filter((c) => c.path.endsWith("/folder/delete"))
      .map((c) => c.body),
  ).toEqual([
    {
      deletion_request_id: deletionId,
      confirm: true,
      permanent_deletion_verified: false,
    },
    {
      deletion_request_id: deletionId,
      confirm: true,
      permanent_deletion_verified: false,
    },
  ]);
});

test("deferral sends Moscow time with an explicit timezone and a reason", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.order.status = "completed";
  state.deletion = deletion();
  state.folder = folder();
  await page.goto(`/admin/orders/${orderId}`);
  await page.getByLabel("Отложить до (МСК)").fill("2030-01-02T14:30");
  await page
    .getByLabel("Причина отсрочки")
    .fill("Поступили уточнения по email");
  await page
    .getByRole("button", { name: "Отложить удаление", exact: true })
    .click();
  await expect(
    page.getByText("Удаление отложено.", { exact: true }),
  ).toBeVisible();
  expect(state.calls.find((c) => c.path.endsWith("/defer"))!.body).toEqual({
    deletion_request_id: deletionId,
    deferred_until: "2030-01-02T11:30:00.000Z",
    note: "Поступили уточнения по email",
  });
  expect(state.deleteCount).toBe(0);
});

test("admin layout remains usable on wide and narrow screens", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.order.status = "in_progress";
  state.agreement = agreement("approved", 3);
  state.folder = folder();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/admin/orders/${orderId}`);
  await expect(
    page.getByRole("heading", { name: "Заказ № 217", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "/tmp/sinegor-f2-order-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "/tmp/sinegor-f2-order-mobile.png",
    fullPage: true,
  });
});

test("customer edits preserve nullable fields and order history remains accessible", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.goto(`/admin/customers/${customerId}`);
  await page.getByLabel("Имя или наименование").fill("Обновлённое имя");
  await page.getByLabel("Телефон", { exact: true }).fill("");
  await page
    .getByRole("button", { name: "Сохранить карточку", exact: true })
    .click();
  await expect(
    page.getByText("Карточка сохранена.", { exact: true }),
  ).toBeVisible();
  expect(state.calls.find((c) => c.method === "PATCH")!.body).toEqual({
    display_name: "Обновлённое имя",
    phone: null,
  });
  await page.getByRole("link", { name: "№ 217", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Заказ № 217", exact: true }),
  ).toBeVisible();
});

test("terms can be edited before agreement and status filters apply server-side", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.goto(`/admin/orders/${orderId}`);
  await page.getByLabel("Согласованные условия").fill("Изменённые условия");
  await page
    .getByRole("button", { name: "Сохранить условия", exact: true })
    .click();
  await expect(
    page.getByText("Условия сохранены.", { exact: true }),
  ).toBeVisible();
  expect(
    state.calls.find((c) => c.method === "PUT" && c.path.endsWith("/terms"))!
      .body?.description,
  ).toBe("Изменённые условия");
  await page.getByRole("link", { name: "Заказы", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Статус", exact: true })
    .selectOption("completed");
  await page.getByRole("button", { name: "Применить", exact: true }).click();
  await expect(
    page.getByText("Заказы с выбранными фильтрами не найдены.", {
      exact: true,
    }),
  ).toBeVisible();
});

test("agreement can be approved or rejected only after review of the downloaded version", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.agreement = agreement();
  await page.goto(`/admin/orders/${orderId}`);
  await page
    .getByRole("button", { name: "Скачать PDF заказчика", exact: true })
    .click();
  await page
    .getByLabel("Я проверил документ и подписи", { exact: false })
    .check();
  await page
    .getByRole("combobox", { name: "Решение", exact: true })
    .selectOption("reject");
  await page
    .getByLabel("Причина отклонения", { exact: true })
    .fill("Подпишите вторую страницу");
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await page
    .getByRole("button", { name: "Отклонить версию", exact: true })
    .click();
  await expect(
    page.getByText("Соглашение отклонено.", { exact: true }),
  ).toBeVisible();
  expect(
    state.calls.find((c) => c.path.endsWith("/agreement/reject"))!.body,
  ).toEqual({ revision: 2, reason: "Подпишите вторую страницу" });
  state.agreement = agreement("under_review", 4);
  state.pdfRevision = 4;
  await page
    .getByRole("button", { name: "Обновить карточку", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Скачать PDF заказчика", exact: true })
    .click();
  await page
    .getByLabel("Я проверил документ и подписи", { exact: false })
    .check();
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await page
    .getByRole("button", { name: "Утвердить версию", exact: true })
    .click();
  await expect(
    page.getByText("Соглашение утверждено.", { exact: true }),
  ).toBeVisible();
  expect(
    state.calls.find((c) => c.path.endsWith("/agreement/approve"))!.body,
  ).toEqual({ revision: 4 });
  await expect(
    page.getByText("Ожидает материалы", { exact: true }),
  ).toBeVisible();
});

test("different PDF response revision cannot be replaced by the metadata revision", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.agreement = agreement();
  state.pdfRevision = 1;
  await page.goto(`/admin/orders/${orderId}`);
  await page
    .getByRole("button", { name: "Скачать PDF заказчика", exact: true })
    .click();
  await expect(
    page.getByText("Скачанная версия: 1", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Продолжить", exact: true }),
  ).toBeDisabled();
  expect(state.calls.some((c) => c.path.endsWith("/agreement/approve"))).toBe(
    false,
  );
});

test("folder creation and sharing require manual confirmation and expose only a Disk link", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.goto(`/admin/orders/${orderId}`);
  await page
    .getByRole("button", { name: "Создать папку заказа", exact: true })
    .click();
  await expect(
    page.getByText("Папка создана и привязана.", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Ссылка для заказчика", { exact: true })
    .fill("https://disk.yandex.ru/invite/synthetic");
  await page
    .getByLabel("Я вручную предоставил заказчику доступ", { exact: false })
    .check();
  await page
    .getByRole("button", { name: "Сохранить клиентскую ссылку", exact: true })
    .click();
  await expect(
    page.getByText("Клиентская ссылка сохранена.", { exact: true }),
  ).toBeVisible();
  expect(
    state.calls.find((c) => c.path.endsWith("/folder/link"))!.body,
  ).toEqual({
    folder_url: "https://disk.yandex.ru/invite/synthetic",
    access_granted: true,
  });
  await page
    .getByRole("button", { name: "Получить ссылку для открытия", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: "Открыть папку на Диске", exact: false }),
  ).toHaveAttribute(
    "href",
    "https://disk.yandex.ru/client/disk/SINEGOR/orders/order-217",
  );
});

test("starting work and cancellation never bypass their confirmations", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.order.status = "awaiting_materials";
  state.agreement = agreement("approved", 3);
  await page.goto(`/admin/orders/${orderId}`);
  await page
    .getByLabel("Я получил материалы и подтверждаю начало работы")
    .check();
  await page
    .getByRole("button", { name: "Начать работу", exact: true })
    .click();
  await expect(
    page.getByText("Заказ принят в работу.", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Отменить заказ", exact: true })
    .click();
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  expect(state.order.status).toBe("in_progress");
  await page
    .getByRole("button", { name: "Отменить заказ", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Подтвердить отмену заказа", exact: true })
    .click();
  await expect(page.getByText("Заказ отменён.", { exact: true })).toBeVisible();
  expect(state.order.status).toBe("cancelled");
  expect(state.deleteCount).toBe(0);
});

test("session expiry during a mutation returns to admin login", async ({
  page,
}) => {
  const state = await mockApi(page);
  await page.goto(`/admin/customers/${customerId}`);
  await expect(
    page.getByRole("heading", { name: "Иван Петров", exact: true }),
  ).toBeVisible();
  state.authenticated = false;
  await page
    .getByRole("button", { name: "Сохранить карточку", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Вход администратора", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Иван Петров", { exact: true })).toHaveCount(0);
});

test("manual permanent deletion verification is opt-in after a lost response", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.order.status = "completed";
  state.deletion = deletion();
  state.deletion.status = "error";
  state.folder = folder();
  state.folder.deletion_started_at = "2026-10-01T10:00:00Z";
  await page.goto(`/admin/orders/${orderId}`);
  await expect(
    page.getByRole("button", { name: "Отложить удаление", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", {
      name: "Проверить / повторить операцию удаления",
      exact: true,
    })
    .click();
  await page
    .getByLabel("Подтверждаю запуск или проверку", { exact: false })
    .check();
  await page
    .getByLabel("После потери ответа я лично проверил", { exact: false })
    .check();
  await page
    .getByRole("button", { name: "Подтвердить операцию удаления", exact: true })
    .click();
  await expect.poll(() => state.deleteCount).toBe(1);
  expect(
    state.calls.find((c) => c.path.endsWith("/folder/delete"))!.body
      ?.permanent_deletion_verified,
  ).toBe(true);
});

test("in-flight deletion keeps its confirmation dialog open until a response", async ({
  page,
}) => {
  const state = await mockApi(page);
  state.order.status = "completed";
  state.deletion = deletion();
  state.deletion.status = "confirmed";
  state.folder = folder();
  await page.goto(`/admin/orders/${orderId}`);
  await page
    .getByRole("button", { name: "Удалить папку окончательно", exact: true })
    .click();
  await page
    .getByLabel("Подтверждаю запуск или проверку", { exact: false })
    .check();
  let release!: () => void;
  state.mutationGate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page
    .getByRole("button", { name: "Подтвердить операцию удаления", exact: true })
    .click();
  await expect
    .poll(
      () => state.calls.filter((c) => c.path.endsWith("/folder/delete")).length,
    )
    .toBe(1);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog").getByRole("status")).toContainText(
    "Выполняется",
  );
  await expect(
    page.getByRole("button", { name: "Закрыть", exact: true }),
  ).toBeDisabled();
  state.mutationGate = null;
  release();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  expect(state.deleteCount).toBe(1);
});

test("private SSR returns an uncached skeleton without customer data", async ({
  page,
}) => {
  await mockApi(page);
  const response = await page.request.get(`/admin/orders/${orderId}`);
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toBe("no-store");
  expect(response.headers()["referrer-policy"]).toBe("no-referrer");
  const html = await response.text();
  expect(html).toContain("Загрузка административной панели");
  expect(html).not.toContain("client@example.test");
  expect(html).not.toContain("Согласованные условия");
});
