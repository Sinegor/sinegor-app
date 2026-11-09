import { useRef, useState } from "react";
import { browserApi } from "../lib/api/client";
import { message } from "../lib/admin/api";
import { Form, Field, Button, Notice } from "./ui";
import { useAnalytics } from "./public-analytics";

function emailError(input: HTMLInputElement) {
  if (!input.value.trim()) return "Укажите email.";
  return input.validity.typeMismatch || input.value.length > 320
    ? "Укажите корректный email."
    : "";
}

function normalizePhone(value: string) {
  return value.replace(/[ ()-]/g, "");
}

function phoneError(value: string) {
  if (!value.trim()) return "Укажите телефон.";
  return value.length > 50 ||
    !/^\+[1-9][0-9]{6,14}$/.test(normalizePhone(value))
    ? "Укажите телефон в международном формате: + и 7–15 цифр."
    : "";
}

export function Consultation({ onSuccess }: { onSuccess?: () => void }) {
  const analytics = useAnalytics();
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({ email: "", phone: "" });
  const locked = useRef(false);
  return (
    <section id="consultation" className="card consultation">
      {!sent && (
        <>
          <h2>Обсудим вашу задачу</h2>
          <p>
            Оставьте email и телефон для предварительной консультации. Объём,
            сроки и стоимость согласуются индивидуально; оплата производится вне
            сайта.
          </p>
          <p>
            Для передачи материалов потребуется собственный аккаунт Яндекса с
            доступом к Яндекс Диску. Документы передаются через общую папку
            после оформления заказа.
          </p>
        </>
      )}
      {sent ? (
        <Notice tone="success">
          Заявка принята. Исполнитель свяжется с вами по указанным контактам.
        </Notice>
      ) : (
        <Form
          method="post"
          noValidate
          busy={busy}
          error={error}
          onSubmit={async (event) => {
            event.preventDefault();
            if (locked.current) return;
            const form = event.currentTarget;
            const emailInput = form.elements.namedItem(
              "email",
            ) as HTMLInputElement;
            const phoneInput = form.elements.namedItem(
              "phone",
            ) as HTMLInputElement;
            const errors = {
              email: emailError(emailInput),
              phone: phoneError(phoneInput.value),
            };
            setFieldErrors(errors);
            setError("");
            if (errors.email || errors.phone) {
              (errors.email ? emailInput : phoneInput).focus();
              return;
            }
            const email = emailInput.value.trim().toLowerCase();
            const phone = normalizePhone(phoneInput.value);
            locked.current = true;
            setBusy(true);
            try {
              await browserApi().POST("/api/consultations", {
                body: { email, phone },
              });
              setSent(true);
              onSuccess?.();
              analytics("consultation_submit");
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
            error={fieldErrors.email}
            onBlur={(event) => {
              const error = emailError(event.currentTarget);
              setFieldErrors((current) => ({ ...current, email: error }));
            }}
            onChange={() => {
              setFieldErrors((current) => ({ ...current, email: "" }));
            }}
          />
          <Field
            label="Ваш телефон"
            name="phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            placeholder="+7 (999) 123-45-67"
            maxLength={50}
            required
            error={fieldErrors.phone}
            onBlur={(event) => {
              const error = phoneError(event.currentTarget.value);
              setFieldErrors((current) => ({ ...current, phone: error }));
            }}
            onChange={() => {
              setFieldErrors((current) => ({ ...current, phone: "" }));
            }}
          />
          <p>
            Оба поля обязательны. Телефон укажите с кодом страны, начиная с +.
            Материалы дела и конфиденциальные сведения для заявки не нужны.
          </p>
          <Button type="submit">
            {busy ? "Отправка…" : "Запросить консультацию"}
          </Button>
        </Form>
      )}
    </section>
  );
}
