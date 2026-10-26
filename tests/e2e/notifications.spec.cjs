const { test, expect, control, data, runtimeErrors } = require("./helpers.cjs");

test("consultation delivers both normalized contacts through the real Telegram adapter", async ({
  page,
}) => {
  await page.goto("/contacts");
  await page
    .getByLabel("Ваш email", { exact: true })
    .fill("Reader@Example.org");
  await page
    .getByLabel("Ваш телефон", { exact: true })
    .fill("+44 (20) 7946-0958");
  await page
    .getByRole("button", { name: "Запросить консультацию", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Заявка принята");
  await expect.poll(() => data("notifications").status).toBe("sent");
  const telegram = await control("/telegram");
  expect(telegram.messages).toContain(
    "SINEGOR — заявка на консультацию\nEmail: reader@example.org\nТелефон: +442079460958",
  );
  expect(data("notifications").contact_cleared).toBe(true);
});

test("consultation survives Telegram outage and the real worker clears delivered contact data", async ({
  page,
}) => {
  const errors = runtimeErrors(page);
  try {
    await control("/mode", { telegram_error: true });
    await page.goto("/contacts");
    await page
      .getByLabel("Ваш email", { exact: true })
      .fill("consultation@example.org");
    await page
      .getByLabel("Ваш телефон", { exact: true })
      .fill("+7 (999) 123-45-67");
    await page
      .getByRole("button", { name: "Запросить консультацию", exact: true })
      .click();
    await expect(
      page.getByText(
        "Заявка принята. Исполнитель свяжется с вами по указанным контактам.",
        { exact: true },
      ),
    ).toBeVisible();
    await expect.poll(() => data("notifications").attempts).toBeGreaterThan(0);
    expect(data("notifications").status).toBe("pending");
    expect(data("notifications").contacts_retained).toBe(true);
    await control("/mode", { telegram_error: false });
    data("retry_notification");
    data("job", { name: "process_notifications" });
    const delivered = data("notifications");
    expect(delivered.status).toBe("sent");
    expect(delivered.contact_cleared).toBe(true);
    const message =
      "SINEGOR — заявка на консультацию\nEmail: consultation@example.org\nТелефон: +79991234567";
    const telegram = await control("/telegram");
    expect(telegram.messages.filter((text) => text === message)).toHaveLength(
      1,
    );
    data("job", { name: "process_notifications" });
    expect((await control("/telegram")).messages).toEqual(telegram.messages);
    expect(errors.length).toBe(0);
  } finally {
    await control("/mode", { telegram_error: false });
  }
});
