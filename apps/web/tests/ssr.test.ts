import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { Field, Table, Form, Button } from "../app/components/ui";

describe("accessible foundation", () => {
  it("associates label and validation error with the field", () => {
    const html = renderToStaticMarkup(
      createElement(Field, {
        id: "email",
        label: "Email",
        error: "Введите email",
      }),
    );
    expect(html).toContain('for="email"');
    expect(html).toContain('aria-describedby="email-error"');
    expect(html).toContain('aria-invalid="true"');
    expect(html).toContain('role="alert"');
  });
  it("disables a busy form and does not submit generic buttons", () => {
    const html = renderToStaticMarkup(
      createElement(Form, {
        busy: true,
        children: createElement(Button, { children: "Отправить" }),
      }),
    );
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain('<fieldset disabled="">');
    expect(html).toContain('type="button"');
  });
  it("keeps empty tables meaningful", () => {
    const html = renderToStaticMarkup(
      createElement(Table, {
        caption: "Заказы",
        columns: ["Номер", "Статус"],
        rows: [],
      }),
    );
    expect(html).toContain("<caption>Заказы</caption>");
    expect(html).toContain('scope="col"');
    expect(html).toContain('colSpan="2"');
    expect(html).toContain("Нет данных");
  });
});
