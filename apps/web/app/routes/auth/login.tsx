import { useRef, useState } from "react";
import { browserApi } from "../../lib/api/client";
import { message } from "../../lib/admin/api";
import { Form, Field, Button, Notice } from "../../components/ui";
import { formData, text } from "../../components/customer/common";
export { loginLoader as clientLoader } from "../../lib/api/login";
export { SessionLoading as HydrateFallback } from "../../components/session-status";
export { headers } from "../../layouts/customer";
export const meta = () => [
  { title: "Вход в личный кабинет — SINEGOR LAB" },
  { name: "robots", content: "noindex, nofollow" },
];
export default function CustomerLogin() {
  const [busy, setBusy] = useState(false),
    [sent, setSent] = useState(false),
    [error, setError] = useState("");
  const locked = useRef(false);
  return (
    <div className="login">
      <p className="eyebrow">Личный кабинет</p>
      <h1>Войти по ссылке</h1>
      <p>
        Доступ оформляет исполнитель после консультации. Укажите email, на
        который пришло приглашение. Пароль не нужен.
      </p>
      {sent && (
        <Notice>
          Если для этого email открыт доступ, письмо со ссылкой будет
          отправлено. Проверьте входящие и папку «Спам». Ссылка одноразовая и
          действует ограниченное время.
        </Notice>
      )}
      <Form
        method="post"
        busy={busy}
        error={error}
        onSubmit={async (event) => {
          const data = formData(event);
          if (locked.current) return;
          locked.current = true;
          setBusy(true);
          setSent(false);
          setError("");
          try {
            await browserApi().POST("/api/auth/magic-link/request", {
              body: { email: text(data, "email") },
            });
            setSent(true);
          } catch (error) {
            setError(message(error));
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
        <Button type="submit">
          {busy
            ? "Отправка…"
            : sent
              ? "Запросить новую ссылку"
              : "Получить ссылку для входа"}
        </Button>
      </Form>
    </div>
  );
}
