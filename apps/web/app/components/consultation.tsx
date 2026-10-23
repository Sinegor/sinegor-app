import { useRef, useState } from "react";
import { browserApi } from "../lib/api/client";
import { message } from "../lib/admin/api";
import { Form, Field, Button, Notice } from "./ui";
export function Consultation() {
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const locked = useRef(false);
  return (
    <section id="consultation" className="card consultation">
      <h2>Обсудим вашу задачу</h2>
      <p>
        Оставьте email для предварительной консультации. Объём, сроки и
        стоимость согласуются индивидуально; оплата производится вне сайта.
      </p>
      <p>
        Для передачи материалов потребуется собственный аккаунт Яндекса с
        доступом к Яндекс Диску. Документы передаются через общую папку после
        оформления заказа.
      </p>
      {sent ? (
        <Notice tone="success">
          Заявка принята. Исполнитель свяжется с вами по указанному email.
        </Notice>
      ) : (
        <Form
          method="post"
          busy={busy}
          error={error}
          onSubmit={async (event) => {
            event.preventDefault();
            if (locked.current) return;
            const email = String(
              new FormData(event.currentTarget).get("email") ?? "",
            ).trim();
            locked.current = true;
            setBusy(true);
            setError("");
            try {
              await browserApi().POST("/api/consultations", {
                body: { email },
              });
              setSent(true);
            } catch (cause) {
              setError(message(cause));
            } finally {
              locked.current = false;
              setBusy(false);
            }
          }}
        >
          <Field
            label="Ваш email"
            name="email"
            type="email"
            autoComplete="email"
            maxLength={320}
            required
          />
          <p>
            Укажите только контактный email. Материалы дела и конфиденциальные
            сведения для заявки не нужны.
          </p>
          <Button type="submit">
            {busy ? "Отправка…" : "Запросить консультацию"}
          </Button>
        </Form>
      )}
    </section>
  );
}
