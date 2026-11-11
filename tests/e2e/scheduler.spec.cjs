const fs = require("node:fs");
const path = require("node:path");
const { test, expect, control, data, config } = require("./helpers.cjs");

function schedulerStatus() {
  const file = path.join(config.private, "scheduler-status.json");
  return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : {};
}

test.beforeEach(() => {
  test.skip(!config.scheduler_enabled, "Periodic CLI explicitly disabled");
});

test("periodic CLI picks up a missed initial task without a manual invocation", async () => {
  await expect.poll(() => schedulerStatus().exit_code).toBe(0);
  const previous = schedulerStatus().started_at;
  data("queue_unsent_consultation");
  await expect.poll(() => data("notifications").smtp.status).toBe("sent");
  await expect.poll(() => data("notifications").telegram.status).toBe("sent");
  expect(data("notifications").smtp.attempts).toBe(1);
  expect(data("notifications").telegram.attempts).toBe(1);
  await expect.poll(() => schedulerStatus().started_at).not.toBe(previous);
  expect(schedulerStatus().exit_code).toBe(0);
});

for (const channel of ["smtp", "telegram"]) {
  test(`periodic CLI retries ${channel} without repeating the successful channel`, async ({
    page,
  }) => {
    try {
      await control("/mode", { [channel + "_error"]: true });
      await page.goto("/contacts");
      await page
        .getByLabel("Ваш email", { exact: true })
        .fill(`${channel}-scheduled@example.org`);
      await page
        .getByLabel("Ваш телефон", { exact: true })
        .fill("+79991234567");
      await page
        .getByRole("button", { name: "Запросить консультацию", exact: true })
        .click();
      await expect(page.getByRole("status")).toContainText("Заявка принята");
      await expect.poll(() => data("notifications")[channel].attempts).toBe(1);
      const other = channel === "smtp" ? "telegram" : "smtp";
      await expect.poll(() => data("notifications")[other].status).toBe("sent");
      expect(data("notifications")[channel].status).toBe("pending");
      await control("/mode", { [channel + "_error"]: false });
      // Advance only this synthetic job's eligibility, without changing production retry rules.
      data("retry_notification", { channel });
      await expect
        .poll(() => data("notifications")[channel].status)
        .toBe("sent");
      expect(data("notifications")[channel].attempts).toBe(2);
      expect(data("notifications")[other].attempts).toBe(1);
    } finally {
      await control("/mode", { smtp_error: false, telegram_error: false });
    }
  });
}
