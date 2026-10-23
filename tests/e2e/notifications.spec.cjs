const { test, expect, control, data, runtimeErrors } = require("./helpers.cjs");

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
      .getByRole("button", { name: "Запросить консультацию", exact: true })
      .click();
    await expect(
      page.getByText(
        "Заявка принята. Исполнитель свяжется с вами по указанному email.",
        { exact: true },
      ),
    ).toBeVisible();
    await expect.poll(() => data("notifications").attempts).toBeGreaterThan(0);
    expect(data("notifications").status).toBe("pending");
    await control("/mode", { telegram_error: false });
    data("retry_notification");
    data("job", { name: "process_notifications" });
    const delivered = data("notifications");
    expect(delivered.status).toBe("sent");
    expect(delivered.contact_cleared).toBe(true);
    expect(errors.length).toBe(0);
  } finally {
    await control("/mode", { telegram_error: false });
  }
});
