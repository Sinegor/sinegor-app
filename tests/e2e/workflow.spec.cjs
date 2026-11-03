const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const {
  test,
  expect,
  config,
  data,
  control,
  mutate,
  read,
  download,
  runtimeErrors,
} = require("./helpers.cjs");

async function checkSessionNavigation(page, role) {
  const destination =
    role === "admin" ? "/admin/customers" : "/customer/orders";
  const session = await read(page.request, "/api/auth/session");
  expect(session.role).toBe(role);
  const cookies = await page.context().cookies();
  const cookie = cookies.find((item) => item.name === "sinegor_session");
  expect(!!cookie && cookie.httpOnly && cookie.path === "/").toBe(true);
  await page.getByRole("link", { name: /SINEGOR LAB/ }).click();
  await expect(page).toHaveURL(config.origin + "/");
  // A successful API read here distinguishes a lost session from a broken login page.
  expect(
    (await read(page.request, "/api/auth/session")).id === session.id,
  ).toBe(true);
  expect(
    (await page.context().cookies()).some(
      (item) => item.name === cookie.name && item.value === cookie.value,
    ),
  ).toBe(true);
  for (const login of ["Вход заказчика", "Вход администратора"]) {
    await page.getByRole("link", { name: login, exact: true }).click();
    await expect(page).toHaveURL(config.origin + destination);
    await page.getByRole("link", { name: /SINEGOR LAB/ }).click();
  }
  for (const login of ["/auth/login", "/auth/admin"]) {
    const response = await page.goto(login);
    expect(response.headers()["cache-control"]).toContain("no-store");
    await expect(page).toHaveURL(config.origin + destination);
  }
}

async function checkLogoutHistory(
  page,
  browser,
  role,
  list,
  detail,
  sensitive,
) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(list);
  await expect(
    page.getByRole("button", { name: "Выйти", exact: true }),
  ).toBeVisible();
  await page.goto(detail);
  await expect(
    page.getByText(sensitive, { exact: true }).first(),
  ).toBeVisible();
  // Keep the old cookie only in memory to prove server-side revocation, too.
  const stale = await browser.newContext({
    baseURL: config.origin,
    storageState: await page.context().storageState(),
  });
  try {
    await page.getByRole("button", { name: "Выйти", exact: true }).click();
    const login =
      config.origin + (role === "admin" ? "/auth/admin" : "/auth/login");
    await expect(page).toHaveURL(login);
    for (const context of [page.context(), stale]) {
      expect((await context.request.get("/api/auth/session")).status()).toBe(
        401,
      );
      const response = await context.request.get("/api" + list);
      expect(response.status()).toBe(401);
      expect(response.headers()["cache-control"]).toContain("no-store");
    }
    for (let i = 0; i < 2; i++) {
      await page.goBack();
      await expect(page).toHaveURL(login);
      await expect(page.getByText(sensitive, { exact: true })).toHaveCount(0);
    }
    await page.goto(detail);
    await expect(page).toHaveURL(login);
    await expect(page.getByText(sensitive, { exact: true })).toHaveCount(0);
  } finally {
    await stale.close();
  }
}

test("order lifecycle preserves authorization, delivery, retention and signed agreement", async ({
  page: admin,
  browser,
  request,
}) => {
  const context = await browser.newContext({ baseURL: config.origin });
  const customer = await context.newPage();
  const errors = runtimeErrors(admin);
  const customerErrors = runtimeErrors(customer);
  let customerId, orderId, invitation, signedHash;
  const orderPath = () => "/api/admin/orders/" + orderId;
  const customerPath = () => "/api/customer/orders/" + orderId;
  try {
    await test.step("admin creates customer, invitation and order through the real UI", async () => {
      await admin.goto("/auth/admin");
      await admin
        .getByLabel("Email администратора", { exact: true })
        .fill(config.admin.email);
      await admin
        .getByLabel("Пароль", { exact: true })
        .fill(config.admin.password);
      await admin
        .getByLabel("Одноразовый код", { exact: true })
        .fill(data("totp").code);
      await admin.getByRole("button", { name: "Войти", exact: true }).click();
      await expect(admin).toHaveURL(config.origin + "/admin/customers");
      await checkSessionNavigation(admin, "admin");
      await admin.goto("/admin/customers/new");
      await admin
        .getByLabel("Email", { exact: true })
        .fill("customer@example.org");
      await admin
        .getByLabel("Имя или наименование", { exact: true })
        .fill("E2E заказчик");
      await admin
        .getByRole("button", { name: "Создать и пригласить", exact: true })
        .click();
      await expect(admin).toHaveURL(/\/admin\/customers\/[a-f0-9-]+$/);
      customerId = new URL(admin.url()).pathname.split("/").pop();
      await expect
        .poll(
          async () => !!(await control("/mail?to=customer@example.org")).link,
        )
        .toBe(true);
      invitation = (await control("/mail?to=customer@example.org")).link;
      await admin.goto("/admin/orders/new?customer_id=" + customerId);
      await expect(admin.getByLabel("Согласованные условия")).toHaveCount(0);
      await admin
        .getByLabel("Согласованная стоимость, ₽ (необязательно)")
        .fill("12345,67");
      await admin
        .getByRole("button", { name: "Создать заказ", exact: true })
        .click();
      await expect(admin).toHaveURL(/\/admin\/orders\/[a-f0-9-]+$/);
      orderId = new URL(admin.url()).pathname.split("/").pop();
      const created = await read(admin.request, orderPath());
      expect(created.status).toBe("awaiting_agreement");
      expect(created.description).toBeNull();
      expect(created.agreed_price).toBe("12345.67");
      await expect(admin.getByLabel("Согласованные условия")).toHaveCount(0);
      await admin
        .getByLabel("Согласованная стоимость, ₽ (необязательно)")
        .fill("12500,75");
      await admin
        .getByRole("button", { name: "Сохранить условия", exact: true })
        .click();
      await expect(
        admin.getByText("Условия сохранены.", { exact: true }),
      ).toBeVisible();
      const edited = await read(admin.request, orderPath());
      expect(edited.agreed_price).toBe("12500.75");
      expect(edited.description).toBeNull();
    });
    await test.step("private PDF exchange approves the exact downloaded signed revision", async () => {
      await admin
        .getByLabel("PDF исполнителя", { exact: true })
        .setInputFiles(path.join(config.private, "initial.pdf"));
      await admin
        .getByRole("button", { name: "Загрузить PDF исполнителя", exact: true })
        .click();
      await expect(
        admin.getByRole("button", {
          name: "Скачать PDF исполнителя",
          exact: true,
        }),
      ).toBeVisible();
      await customer.goto(invitation);
      await expect(customer).toHaveURL(config.origin + "/auth/magic-link");
      await customer
        .getByRole("button", { name: "Подтвердить вход", exact: true })
        .click();
      await expect(customer).toHaveURL(config.origin + "/customer/orders");
      await checkSessionNavigation(customer, "customer");
      await customer.goto("/customer/orders/" + orderId);
      const initialHash = await download(
        customer,
        "Скачать соглашение исполнителя",
      );
      signedHash = crypto
        .createHash("sha256")
        .update(fs.readFileSync(path.join(config.private, "signed.pdf")))
        .digest("hex");
      expect(initialHash).not.toBe(signedHash);
      await customer
        .getByLabel("Подписанное соглашение PDF", { exact: true })
        .setInputFiles(path.join(config.private, "signed.pdf"));
      await customer.getByLabel("Отправляю соглашение с моей подписью").check();
      await customer
        .getByRole("button", { name: "Отправить подписанный PDF", exact: true })
        .click();
      await expect(
        customer.getByText("Ваш PDF получен и ожидает проверки исполнителем.", {
          exact: true,
        }),
      ).toBeVisible();
      await admin.reload();
      expect(await download(admin, "Скачать PDF заказчика")).toBe(signedHash);
      await admin
        .getByLabel("Я проверил документ и подписи в скачанном PDF")
        .check();
      await admin
        .getByRole("button", { name: "Продолжить", exact: true })
        .click();
      await admin
        .getByRole("button", { name: "Утвердить версию", exact: true })
        .click();
      await expect(
        admin.getByText("Соглашение утверждено.", { exact: true }),
      ).toBeVisible();
      expect((await read(admin.request, orderPath())).status).toBe(
        "awaiting_materials",
      );
      expect(
        (await read(admin.request, orderPath() + "/agreement")).final_sha256,
      ).toBe(signedHash);
      expect(
        (await admin.request.get(orderPath() + "/agreement/initial")).status(),
      ).toBe(404);
    });
    await test.step("a real session cannot access another customer's order or admin operations", async () => {
      const created = await mutate(admin.request, "/api/admin/customers", {
        email: "other@example.org",
      });
      expect(created.status()).toBe(201);
      const otherOrder = await mutate(admin.request, "/api/admin/orders", {
        customer_id: (await created.json()).id,
        service_type: "technical_preparation",
      });
      expect(otherOrder.status()).toBe(201);
      const foreignId = (await otherOrder.json()).id;
      expect(
        (
          await customer.request.get("/api/customer/orders/" + foreignId)
        ).status(),
      ).toBe(404);
      expect(
        (
          await customer.request.get(
            "/api/customer/orders/" + foreignId + "/agreement/initial",
          )
        ).status(),
      ).toBe(404);
      expect((await customer.request.get("/api/admin/orders")).status()).toBe(
        403,
      );
      expect(
        (await request.get(customerPath() + "/agreement/final")).status(),
      ).toBe(401);
      const reused = await mutate(request, "/api/auth/magic-link/verify", {
        token: new URL(invitation).hash.slice(7),
      });
      expect(reused.status()).toBe(401);
    });
    await test.step("Disk link and material handover cross real UI/API boundaries", async () => {
      await admin
        .getByLabel("Путь существующей папки")
        .fill("disk:/E2E/missing");
      await admin
        .getByLabel("Я проверил принадлежность папки этому заказу")
        .check();
      await admin
        .getByRole("button", {
          name: "Привязать существующую папку",
          exact: true,
        })
        .click();
      await expect(admin.getByRole("alert")).toContainText("Папка не найдена");
      expect((await admin.request.get(orderPath() + "/folder")).status()).toBe(
        404,
      );
      await admin
        .getByLabel("Основа имени папки", { exact: false })
        .fill("Финансовые документы");
      await admin
        .getByRole("button", { name: "Создать папку заказа", exact: true })
        .click();
      await expect(
        admin.getByText("Папка создана и привязана.", { exact: true }),
      ).toBeVisible();
      const bound = await read(admin.request, orderPath() + "/folder");
      const orderNumber = (await read(admin.request, orderPath())).number;
      expect(bound.disk_path).toMatch(
        new RegExp(
          `^disk:/E2E/Финансовые_документы_${String(orderNumber).padStart(3, "0")}_[0-9]{4}-[0-9]{2}-[0-9]{2}$`,
        ),
      );
      await admin
        .getByLabel("Ссылка для заказчика", { exact: true })
        .fill("https://disk.yandex.ru/client/disk/E2E/order-" + orderId);
      await admin
        .getByLabel("Я вручную предоставил заказчику доступ к этой папке")
        .check();
      await admin
        .getByRole("button", {
          name: "Сохранить клиентскую ссылку",
          exact: true,
        })
        .click();
      await expect(
        admin.getByText("Клиентская ссылка сохранена.", { exact: true }),
      ).toBeVisible();
      await expect(
        admin.getByRole("heading", { name: "Оплата", exact: true }),
      ).toHaveCount(0);
      expect((await read(admin.request, orderPath() + "/payment")).status).toBe(
        "unpaid",
      );
      await customer.reload();
      await expect(
        customer.getByRole("link", {
          name: "Открыть папку на Яндекс Диске",
          exact: false,
        }),
      ).toBeVisible();
      expect(await customer.locator('input[type="file"]').count()).toBe(0);
      await customer
        .getByLabel("Я завершил передачу материалов", { exact: false })
        .check();
      await customer
        .getByRole("button", {
          name: "Подтвердить передачу материалов",
          exact: true,
        })
        .click();
      await expect
        .poll(
          async () =>
            !!(await read(customer.request, customerPath() + "/materials")),
        )
        .toBe(true);
      await admin.reload();
      await admin
        .getByLabel("Я получил материалы и подтверждаю начало работы")
        .check();
      await admin
        .getByRole("button", { name: "Начать работу", exact: true })
        .click();
      await expect(
        admin.getByText("Заказ принят в работу.", { exact: true }),
      ).toBeVisible();
    });
    await test.step("SMTP failure cannot start retention before successful delivery", async () => {
      await control("/mode", { smtp_error: true });
      await admin.getByLabel("Результат размещён в папке заказа").check();
      await admin
        .getByLabel("Я вручную изменил права заказчика на просмотр")
        .check();
      await admin
        .getByRole("button", { name: "Зафиксировать готовность", exact: true })
        .click();
      await expect(admin.getByRole("alert").first()).toBeVisible();
      const pending = await read(admin.request, orderPath());
      expect(pending.status).toBe("in_progress");
      expect(pending.result_notified_at).toBe(null);
      await control("/mode", { smtp_error: false });
      await admin.getByLabel("Результат размещён в папке заказа").check();
      await admin
        .getByLabel("Я вручную изменил права заказчика на просмотр")
        .check();
      await admin
        .getByRole("button", { name: "Зафиксировать готовность", exact: true })
        .click();
      await expect
        .poll(async () => (await read(admin.request, orderPath())).status)
        .toBe("result_ready");
      await customer.reload();
      await expect(
        customer.getByText("Результат предоставлен, уведомление отправлено", {
          exact: false,
        }),
      ).toBeVisible();
    });
    await test.step("customer permission and admin deferral do not execute deletion", async () => {
      await customer
        .getByRole("button", {
          name: "Разрешить удаление материалов",
          exact: true,
        })
        .click();
      await customer
        .getByLabel("Разрешаю удалить материалы", { exact: false })
        .check();
      await customer
        .getByRole("button", {
          name: "Подтвердить разрешение на удаление",
          exact: true,
        })
        .click();
      await expect
        .poll(
          async () =>
            (await read(customer.request, customerPath() + "/deletion-request"))
              ?.status,
        )
        .toBe("waiting");
      const deletion = await read(
        customer.request,
        customerPath() + "/deletion-request",
      );
      expect(
        (
          await mutate(admin.request, orderPath() + "/folder/delete", {
            deletion_request_id: deletion.id,
            confirm: true,
          })
        ).status(),
      ).toBe(409);
      await admin.reload();
      const tomorrowMoscow = new Date(Date.now() + 27 * 3600000)
        .toISOString()
        .slice(0, 16);
      await admin
        .getByLabel("Отложить до (МСК)", { exact: true })
        .fill(tomorrowMoscow);
      await admin
        .getByLabel("Причина отсрочки", { exact: true })
        .fill("E2E внешнее уточнение");
      await admin
        .getByRole("button", { name: "Отложить удаление", exact: true })
        .click();
      await expect(
        admin.getByText("Удаление отложено.", { exact: true }),
      ).toBeVisible();
      expect(
        (await read(admin.request, orderPath() + "/folder")).deleted_at,
      ).toBe(null);
    });
    await test.step("real CLI completes after 14 days independently of deletion and only once", async () => {
      data("ready_time", { order_id: orderId, seconds_after: -60 });
      data("job", { name: "process_orders" });
      expect((await read(admin.request, orderPath())).status).toBe(
        "result_ready",
      );
      data("ready_time", { order_id: orderId, seconds_after: 60 });
      data("job", { name: "process_orders" });
      expect((await read(admin.request, orderPath())).status).toBe("completed");
      expect(
        (await read(admin.request, orderPath() + "/deletion-request")).status,
      ).toBe("deferred");
      const before = data("inspect", { order_id: orderId });
      data("job", { name: "process_orders" });
      expect(data("inspect", { order_id: orderId }).events).toBe(before.events);
      data("expire_deferral", { order_id: orderId });
      data("job", { name: "process_orders" });
    });
    await test.step("explicit admin confirmation and async verification preserve the final PDF", async () => {
      await admin.reload();
      await admin
        .getByRole("button", {
          name: "Подтвердить решение об удалении",
          exact: true,
        })
        .click();
      await admin.getByRole("button", { name: "Закрыть", exact: true }).click();
      expect(
        (await read(admin.request, orderPath() + "/deletion-request")).status,
      ).toBe("waiting");
      await admin
        .getByRole("button", {
          name: "Подтвердить решение об удалении",
          exact: true,
        })
        .click();
      await admin
        .getByLabel("Я проверил обращения заказчика и подтверждаю решение.", {
          exact: false,
        })
        .check();
      await admin
        .getByRole("button", { name: "Подтвердить решение", exact: true })
        .click();
      await expect(
        admin.getByText(
          "Решение сохранено. Для удаления требуется отдельное действие.",
          { exact: true },
        ),
      ).toBeVisible();
      expect(
        (await read(admin.request, orderPath() + "/folder")).deleted_at,
      ).toBe(null);
      await admin
        .getByRole("button", {
          name: "Удалить папку окончательно",
          exact: true,
        })
        .click();
      await admin
        .getByLabel(
          "Подтверждаю запуск или проверку окончательного удаления именно этой папки",
        )
        .check();
      await admin
        .getByRole("button", {
          name: "Подтвердить операцию удаления",
          exact: true,
        })
        .click();
      await expect(
        admin.getByRole("button", {
          name: "Проверить / повторить операцию удаления",
          exact: true,
        }),
      ).toBeVisible();
      expect(
        (await read(admin.request, orderPath() + "/folder")).deleted_at,
      ).toBe(null);
      await admin
        .getByRole("button", {
          name: "Проверить / повторить операцию удаления",
          exact: true,
        })
        .click();
      await admin
        .getByLabel(
          "Подтверждаю запуск или проверку окончательного удаления именно этой папки",
        )
        .check();
      await admin
        .getByRole("button", {
          name: "Подтвердить операцию удаления",
          exact: true,
        })
        .click();
      await expect
        .poll(
          async () =>
            (await read(admin.request, orderPath() + "/deletion-request"))
              .status,
        )
        .toBe("performed");
      await customer.reload();
      expect(data("inspect", { order_id: orderId }).agreement_hash).toBe(
        signedHash,
      );
      expect(await download(customer, "Скачать подписанное соглашение")).toBe(
        signedHash,
      );
      expect(
        (await customer.request.get(customerPath() + "/folder")).status(),
      ).toBe(404);
      expect(data("inspect", { order_id: orderId }).events).toBeGreaterThan(15);
      const privateOrderTitle = `Заказ № ${(await read(admin.request, orderPath())).number}`;
      const html = await (
        await request.get("/customer/orders/" + orderId)
      ).text();
      expect(html.includes(privateOrderTitle)).toBe(false);
      for (const width of [1440, 390]) {
        await customer.setViewportSize({ width, height: 900 });
        expect(
          await customer.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        ).toBe(true);
      }
      await checkLogoutHistory(
        customer,
        browser,
        "customer",
        "/customer/orders",
        "/customer/orders/" + orderId,
        privateOrderTitle,
      );
      await checkLogoutHistory(
        admin,
        browser,
        "admin",
        "/admin/customers",
        "/admin/customers/" + customerId,
        "E2E заказчик",
      );
      expect(customerErrors.length).toBe(0);
      expect(errors.length).toBe(0);
    });
  } finally {
    await control("/mode", { smtp_error: false });
    await context.close();
  }
});
