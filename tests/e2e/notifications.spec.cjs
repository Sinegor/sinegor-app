const {
  test,
  expect,
  control,
  data,
  config,
  runtimeErrors,
} = require("./helpers.cjs");

const notice = "Поступила новая заявка на консультацию";
const mailbox =
  "/mail?to=" + encodeURIComponent(config.api_env.NOTIFICATION_ADMIN_EMAIL);

async function submit(page, email, phone) {
  await page.goto("/contacts");
  await page.getByLabel("Ваш email", { exact: true }).fill(email);
  await page.getByLabel("Ваш телефон", { exact: true }).fill(phone);
  await page
    .getByRole("button", { name: "Запросить консультацию", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Заявка принята");
}

async function checkContacts(email, phone, beforeTelegram) {
  const received = await control(mailbox);
  expect(
    received.consultations.filter(
      (body) =>
        body.includes(`Email: ${email}`) && body.includes(`Телефон: ${phone}`),
    ),
  ).toHaveLength(1);
  expect((await control("/mail?to=" + encodeURIComponent(email))).count).toBe(
    0,
  );
  const telegram = await control("/telegram");
  expect(telegram.messages.slice(beforeTelegram)).toEqual([notice]);
}

test("consultation sends normalized contacts only to SMTP and a fixed notice to Telegram", async ({
  page,
}) => {
  const errors = runtimeErrors(page);
  const beforeMail = (await control(mailbox)).count;
  const beforeTelegram = (await control("/telegram")).messages.length;
  await submit(page, "Reader@Example.org", "+44 (20) 7946-0958");
  await expect.poll(() => data("notifications").smtp.status).toBe("sent");
  await expect.poll(() => data("notifications").telegram.status).toBe("sent");
  expect(data("notifications").smtp.contact_cleared).toBe(true);
  expect(data("notifications").telegram.contact_cleared).toBe(true);
  expect((await control(mailbox)).count).toBe(beforeMail + 1);
  expect((await control("/telegram")).messages).toHaveLength(
    beforeTelegram + 1,
  );
  await checkContacts("reader@example.org", "+442079460958", beforeTelegram);
  data("job", { name: "process_notifications" });
  expect((await control(mailbox)).count).toBe(beforeMail + 1);
  expect((await control("/telegram")).messages).toHaveLength(
    beforeTelegram + 1,
  );
  expect(errors).toEqual([]);
});

for (const failedChannel of ["smtp", "telegram"]) {
  test(`consultation retries ${failedChannel} through the real worker without repeating the successful channel`, async ({
    page,
  }) => {
    const errors = runtimeErrors(page);
    const beforeMail = (await control(mailbox)).count;
    const beforeTelegram = (await control("/telegram")).messages.length;
    const email = `${failedChannel}-outage@example.org`;
    const succeededChannel = failedChannel === "smtp" ? "telegram" : "smtp";
    try {
      await control("/mode", { [failedChannel + "_error"]: true });
      await submit(page, email, "+7 (999) 123-45-67");
      await expect
        .poll(() => data("notifications")[failedChannel].attempts)
        .toBe(1);
      await expect
        .poll(() => data("notifications")[succeededChannel].status)
        .toBe("sent");
      const pending = data("notifications");
      expect(pending[failedChannel].status).toBe("pending");
      expect(pending[failedChannel].retry_in_seconds).toBeGreaterThan(1400);
      expect(pending[failedChannel].retry_in_seconds).toBeLessThanOrEqual(2160);
      expect(pending.smtp.contacts_retained).toBe(failedChannel === "smtp");
      expect(pending.telegram.contact_cleared).toBe(true);
      expect((await control(mailbox)).count).toBe(
        beforeMail + (failedChannel === "smtp" ? 0 : 1),
      );
      expect((await control("/telegram")).messages).toHaveLength(
        beforeTelegram + (failedChannel === "telegram" ? 0 : 1),
      );
      await control("/mode", { [failedChannel + "_error"]: false });
      data("retry_notification", { channel: failedChannel });
      data("job", { name: "process_notifications" });
      const delivered = data("notifications");
      expect(delivered.smtp.status).toBe("sent");
      expect(delivered.telegram.status).toBe("sent");
      expect(delivered[failedChannel].attempts).toBe(2);
      expect(delivered[succeededChannel].attempts).toBe(1);
      expect(delivered.smtp.contact_cleared).toBe(true);
      await checkContacts(email, "+79991234567", beforeTelegram);
      data("job", { name: "process_notifications" });
      expect((await control(mailbox)).count).toBe(beforeMail + 1);
      expect((await control("/telegram")).messages).toHaveLength(
        beforeTelegram + 1,
      );
      expect(errors).toEqual([]);
    } finally {
      await control("/mode", { smtp_error: false, telegram_error: false });
    }
  });
}

test("administrator retries and manually handles consultation delivery problems through the real panel", async ({
  page,
}) => {
  const errors = runtimeErrors(page);
  const beforeMail = (await control(mailbox)).count;
  const beforeTelegram = (await control("/telegram")).messages.length;
  try {
    expect((await page.request.get("/api/admin/consultations")).status()).toBe(
      401,
    );
    await control("/mode", { smtp_error: true });
    await submit(page, "panel-retry@example.org", "+79991234567");
    await expect.poll(() => data("notifications").smtp.status).toBe("pending");
    await page.goto("/auth/admin");
    await page
      .getByLabel("Email администратора", { exact: true })
      .fill(data("panel_admin").email);
    await page
      .getByLabel("Пароль", { exact: true })
      .fill(config.admin.password);
    await page
      .getByLabel("Одноразовый код", { exact: true })
      .fill(data("totp").code);
    await page.getByRole("button", { name: "Войти", exact: true }).click();
    await expect(page).toHaveURL(config.origin + "/admin/customers");
    await page
      .getByRole("link", { name: "Доставка заявок", exact: true })
      .click();
    await expect(
      page.getByText("panel-retry@example.org", { exact: true }),
    ).toBeVisible();
    await control("/mode", { smtp_error: false });
    await page
      .getByRole("button", { name: "Повторить отправку: Email", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Подтвердить отправку", exact: true })
      .click();
    await expect.poll(() => data("notifications").smtp.status).toBe("sent");
    await page.getByRole("button", { name: "Обновить", exact: true }).click();
    await expect(
      page.getByText("Недоставленных консультационных заявок нет."),
    ).toBeVisible();
    expect((await control(mailbox)).count).toBe(beforeMail + 1);
    expect((await control("/telegram")).messages).toHaveLength(
      beforeTelegram + 1,
    );

    await control("/mode", { smtp_error: true });
    await submit(page, "panel-handle@example.org", "+79991234567");
    await expect.poll(() => data("notifications").smtp.status).toBe("pending");
    await page.goto("/admin/consultations");
    await expect(
      page.getByText("panel-handle@example.org", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Отметить обработанным", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Подтвердить обработку", exact: true })
      .click();
    await expect
      .poll(() => data("notifications").smtp.status)
      .toBe("cancelled");
    expect(data("notifications").smtp.contact_cleared).toBe(true);
    expect(data("notifications").telegram.status).toBe("sent");
    await page.getByRole("link", { name: "Обработанные", exact: true }).click();
    await expect(
      page.getByText("Обработано вручную", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("panel-handle@example.org", { exact: true }),
    ).toHaveCount(0);
    await control("/mode", { smtp_error: false });
    data("job", { name: "process_notifications" });
    expect((await control(mailbox)).count).toBe(beforeMail + 1);
    expect((await control("/telegram")).messages).toHaveLength(
      beforeTelegram + 2,
    );
    expect(errors).toEqual([]);
  } finally {
    await control("/mode", { smtp_error: false, telegram_error: false });
  }
});
