import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/auth/csrf", (route) =>
    route.fulfill({ json: { csrf_token: "test" } }),
  );
  await page.goto("/contacts");
});

test("required contacts show accessible errors and focus the first invalid field", async ({
  page,
}) => {
  let requests = 0;
  await page.route("**/api/consultations", async (route) => {
    requests++;
    await route.fulfill({ status: 202, json: {} });
  });
  const email = page.getByLabel("Ваш email");
  const phone = page.getByLabel("Ваш телефон");
  await expect(email).toHaveAttribute("required", "");
  await expect(phone).toHaveAttribute("required", "");
  await expect(phone).toHaveAttribute("type", "tel");
  await expect(phone).toHaveAttribute("autocomplete", "tel");
  await page.getByRole("button", { name: "Запросить консультацию" }).click();
  await expect(email).toBeFocused();
  await expect(email).toHaveAttribute("aria-invalid", "true");
  await expect(phone).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByText("Укажите email.", { exact: true })).toBeVisible();
  const phoneError = page.getByText("Укажите телефон.", { exact: true });
  await expect(phoneError).toBeVisible();
  await expect(phone).toHaveAttribute(
    "aria-describedby",
    (await phoneError.getAttribute("id"))!,
  );
  await email.fill("reader@example.com");
  await page.getByRole("button", { name: "Запросить консультацию" }).click();
  await expect(phone).toBeFocused();
  await expect(email).toHaveAttribute("aria-invalid", "false");
  expect(requests).toBe(0);
});

test("invalid values show field errors on blur and prevent submission", async ({
  page,
}) => {
  let requests = 0;
  await page.route("**/api/consultations", async (route) => {
    requests++;
    await route.fulfill({ status: 202, json: {} });
  });
  const email = page.getByLabel("Ваш email");
  const phone = page.getByLabel("Ваш телефон");
  await email.fill("invalid");
  await phone.fill("89991234567");
  await expect(page.getByText("Укажите корректный email.")).toBeVisible();
  await phone.blur();
  await expect(
    page.getByText("Укажите телефон в международном формате: + и 7–15 цифр."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Запросить консультацию" }).click();
  expect(requests).toBe(0);
  await expect(email).toHaveValue("invalid");
  await expect(phone).toHaveValue("89991234567");
});

for (const phone of ["+1234567", "+123456789012345", "+44 (20) 7946-0958"]) {
  test(`international phone ${phone} is accepted and normalized`, async ({
    page,
  }) => {
    await page.route("**/api/consultations", async (route) => {
      expect(route.request().postDataJSON()).toEqual({
        email: "reader@example.com",
        phone: phone.replace(/[ ()-]/g, ""),
      });
      await route.fulfill({ status: 202, json: {} });
    });
    await page.getByLabel("Ваш email").fill("Reader@Example.com");
    await page.getByLabel("Ваш телефон").fill(phone);
    await page.getByRole("button", { name: "Запросить консультацию" }).click();
    await expect(page.getByRole("status")).toContainText(
      "Исполнитель свяжется с вами по указанным контактам.",
    );
  });
}

for (const failure of [403, 422, 500, "network"] as const) {
  test(`API failure ${failure} preserves contacts and permits retry`, async ({
    page,
  }) => {
    let requests = 0;
    await page.route("**/api/consultations", async (route) => {
      requests++;
      expect(route.request().postDataJSON()).toEqual({
        email: "reader@example.com",
        phone: "+79991234567",
      });
      if (requests > 1) {
        await route.fulfill({ status: 202, json: {} });
      } else if (failure === "network") {
        await route.abort("failed");
      } else {
        await route.fulfill({
          status: failure,
          json: { error: { message: "private upstream response" } },
        });
      }
    });
    await page.getByLabel("Ваш email").fill("Reader@Example.com");
    await page.getByLabel("Ваш телефон").fill("+7 (999) 123-45-67");
    await page.getByRole("button", { name: "Запросить консультацию" }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: "Запросить консультацию",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Заявка отправлена", exact: true }),
    ).toHaveCount(0);
    await expect(page.getByRole("alert")).not.toContainText("private");
    await expect(page.getByLabel("Ваш email")).toHaveValue(
      "Reader@Example.com",
    );
    await expect(page.getByLabel("Ваш телефон")).toHaveValue(
      "+7 (999) 123-45-67",
    );
    await page.getByRole("button", { name: "Запросить консультацию" }).click();
    await expect(page.getByRole("status")).toContainText("Заявка принята");
    expect(requests).toBe(2);
  });
}

test("busy form blocks duplicate submission and keeps both contacts", async ({
  page,
}) => {
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => {
    finish = resolve;
  });
  let requests = 0;
  await page.route("**/api/consultations", async (route) => {
    requests++;
    await pending;
    await route.fulfill({ status: 202, json: {} });
  });
  await page.getByLabel("Ваш email").fill("reader@example.com");
  await page.getByLabel("Ваш телефон").fill("+79991234567");
  const form = page.locator("#consultation form");
  await form.evaluate((element: HTMLFormElement) => {
    element.requestSubmit();
    element.requestSubmit();
  });
  await expect(form).toHaveAttribute("aria-busy", "true");
  await expect(page.getByLabel("Ваш email")).toBeDisabled();
  await expect(page.getByLabel("Ваш телефон")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Отправка…" })).toBeDisabled();
  await expect.poll(() => requests).toBe(1);
  finish();
  await expect(page.getByRole("status")).toContainText("Заявка принята");
  expect(requests).toBe(1);
});

for (const width of [320, 390, 1440]) {
  test(`consultation and field errors fit a ${width}px screen`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.getByRole("button", { name: "Запросить консультацию" }).click();
    await expect(page.getByRole("alert")).toHaveCount(2);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    const email = await page.getByLabel("Ваш email").boundingBox();
    const phone = await page.getByLabel("Ваш телефон").boundingBox();
    expect(email!.height).toBeGreaterThanOrEqual(44);
    expect(phone!.height).toBeGreaterThanOrEqual(44);
    expect(phone!.y).toBeGreaterThan(email!.y + email!.height);
    await page.locator("#consultation").screenshot({
      path: `/tmp/sinegor-consultation-work/form-${width}-errors.png`,
    });
  });
}

for (const width of [390, 1440]) {
  test(`consultation page omits contact introduction and shows success after API confirmation ${width}`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const main = page.getByRole("main");
    await expect(
      main.getByRole("heading", {
        level: 1,
        name: "Запросить консультацию",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      main.getByText("IT-лаборатория адвоката Артемьева Д. В.", {
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      main.getByRole("heading", { name: "Контакты", exact: true }),
    ).toHaveCount(0);
    await page.screenshot({
      path: info.outputPath(`consultation-form-${width}.png`),
      fullPage: true,
    });
    let finish!: () => void;
    const pending = new Promise<void>((resolve) => {
      finish = resolve;
    });
    let requests = 0;
    await page.route("**/api/consultations", async (route) => {
      requests++;
      await pending;
      await route.fulfill({ status: 202, json: {} });
    });
    await page.getByLabel("Ваш email").fill("reader@example.test");
    await page.getByLabel("Ваш телефон").fill("+79991234567");
    await page.getByRole("button", { name: "Запросить консультацию" }).click();
    await expect.poll(() => requests).toBe(1);
    await expect(
      main.getByRole("heading", {
        level: 1,
        name: "Запросить консультацию",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      main.getByRole("heading", { name: "Заявка отправлена", exact: true }),
    ).toHaveCount(0);
    finish();
    const heading = main.getByRole("heading", {
      level: 1,
      name: "Заявка отправлена",
      exact: true,
    });
    await expect(heading).toBeVisible();
    await expect(heading).toBeFocused();
    await expect(
      main.getByRole("heading", { name: "Контакты", exact: true }),
    ).toHaveCount(0);
    await expect(
      main.getByText("IT-лаборатория адвоката Артемьева Д. В.", {
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(page.getByRole("status")).toContainText("Заявка принята");
    await expect(page.getByLabel("Ваш email")).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath(`consultation-success-${width}.png`),
      fullPage: true,
    });
    await main.getByRole("link", { name: "На главную", exact: true }).click();
    await expect(page).toHaveURL("/");
    await page.goto("/contacts");
    await expect(
      main.getByRole("heading", {
        level: 1,
        name: "Запросить консультацию",
        exact: true,
      }),
    ).toBeVisible();
    await expect(page.getByLabel("Ваш email")).toBeVisible();
    expect(requests).toBe(1);
  });
}
