import { test, expect } from "@playwright/test";
import { mockApi } from "./mock-api";

test.use({ trace: "off" });

for (const viewport of [
  { width: 1280, height: 900 },
  { width: 390, height: 844 },
]) {
  test.describe(`admin password at ${viewport.width}px`, () => {
    test.use({ viewport });

    test("keyboard toggles preserve credentials without submitting; visible password login keeps CSRF", async ({
      page,
    }, testInfo) => {
      const state = await mockApi(page);
      state.authenticated = false;
      const secret = " synthetic-password-with-spaces ";
      const logs: string[] = [];
      page.on("console", (entry) => logs.push(entry.text()));
      page.on("pageerror", (error) => logs.push(error.message));
      await page.goto("/auth/admin");
      const password = page.getByLabel("Пароль", { exact: true });
      const toggle = page.getByRole("button", {
        name: "Показать пароль",
        exact: true,
      });
      await expect(password).toHaveAttribute("type", "password");
      await expect(password).toHaveAttribute(
        "autocomplete",
        "current-password",
      );
      await expect(toggle).toHaveAttribute("aria-pressed", "false");
      await expect(toggle).toHaveAttribute(
        "aria-controls",
        (await password.getAttribute("id")) as string,
      );
      const bounds = await toggle.boundingBox();
      expect(
        !!bounds &&
          Math.round(bounds.width) >= 44 &&
          Math.round(bounds.height) >= 44,
      ).toBe(true);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: testInfo.outputPath("password-default.png"),
        animations: "disabled",
      });
      await page.getByLabel("Email администратора").fill("admin@example.test");
      await password.fill(secret);
      await page.getByLabel("Одноразовый код").fill("123456");
      await password.focus();
      await page.keyboard.press("Tab");
      await expect(toggle).toBeFocused();
      expect(
        await toggle.evaluate(
          (element) => getComputedStyle(element).outlineStyle !== "none",
        ),
      ).toBe(true);
      await page.keyboard.press("Space");
      const hide = page.getByRole("button", {
        name: "Скрыть пароль",
        exact: true,
      });
      await expect(hide).toHaveAttribute("aria-pressed", "true");
      await expect(password).toHaveAttribute("type", "text");
      expect((await password.inputValue()) === secret).toBe(true);
      await page.keyboard.press("Enter");
      await expect(password).toHaveAttribute("type", "password");
      await expect(toggle).toBeFocused();
      expect((await password.inputValue()) === secret).toBe(true);
      expect(state.calls.filter((call) => call.method === "POST")).toHaveLength(
        0,
      );
      await toggle.click();
      await page.keyboard.press("Tab");
      await expect(page.getByLabel("Одноразовый код")).toBeFocused();
      await page.getByRole("button", { name: "Войти", exact: true }).click();
      await expect(page).toHaveURL("/admin/customers");
      const calls = state.calls.filter(
        (call) => call.path === "/api/auth/admin/login",
      );
      expect(calls).toHaveLength(1);
      expect(calls[0].csrf).toBe("test-csrf");
      expect(calls[0].body?.password === secret).toBe(true);
      expect(Object.keys(calls[0].body!).sort()).toEqual([
        "code",
        "email",
        "password",
      ]);
      expect(calls[0].body?.code).toBe("123456");
      expect(calls[0].body?.email).toBe("admin@example.test");
      expect(logs.some((entry) => entry.includes(secret))).toBe(false);
    });

    test("401 retains the password and toggle; pending form is disabled and hidden retry succeeds", async ({
      page,
    }) => {
      const state = await mockApi(page);
      state.authenticated = false;
      const secret = "synthetic-retry-password";
      let release!: () => void;
      const gate = new Promise<void>((resolve) => {
        release = resolve;
      });
      let first = true;
      await page.route("**/api/auth/admin/login", async (route) => {
        if (!first) return route.fallback();
        first = false;
        await gate;
        return route.fulfill({ status: 401, json: {} });
      });
      await page.goto("/auth/admin");
      await page.getByLabel("Email администратора").fill("admin@example.test");
      const password = page.getByLabel("Пароль", { exact: true });
      await password.fill(secret);
      await page.getByLabel("Одноразовый код").fill("123456");
      await page
        .getByRole("button", { name: "Показать пароль", exact: true })
        .click();
      const toggle = page.getByRole("button", {
        name: "Скрыть пароль",
        exact: true,
      });
      await page.getByRole("button", { name: "Войти", exact: true }).click();
      try {
        await expect(toggle).toBeDisabled();
        await expect(password).toBeDisabled();
      } finally {
        release();
      }
      await expect(page.getByRole("alert")).toContainText(
        "Неверный email, пароль или одноразовый код.",
      );
      await expect(toggle).toBeEnabled();
      await expect(toggle).toHaveAttribute("aria-pressed", "true");
      expect((await password.inputValue()) === secret).toBe(true);
      await toggle.click();
      await expect(password).toHaveAttribute("type", "password");
      await page.getByRole("button", { name: "Войти", exact: true }).click();
      await expect(page).toHaveURL("/admin/customers");
      const login = state.calls.find(
        (call) => call.path === "/api/auth/admin/login",
      )!;
      expect(login.body?.password === secret).toBe(true);
      expect(login.csrf).toBe("test-csrf");
    });
  });
}
