import { useRef, useState } from "react";
import { useNavigate } from "react-router";
import { browserApi, ApiError } from "../../lib/api/client";
import { message } from "../../lib/admin/api";
import { Button, Field, Form } from "../../components/ui";
import { formData, text } from "../../components/admin/common";
export const meta = () => [
  { title: "Вход администратора — SINEGOR LAB" },
  { name: "robots", content: "noindex, nofollow" },
];
export default function AdminLogin() {
  const navigate = useNavigate();
  const locked = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <div className="login">
      <p className="eyebrow">Управление сервисом</p>
      <h1>Вход администратора</h1>
      <p>Пароль и одноразовый код приложения-аутентификатора.</p>
      <Form
        busy={busy}
        error={error}
        method="post"
        onSubmit={async (event) => {
          const data = formData(event);
          if (locked.current) return;
          locked.current = true;
          setBusy(true);
          setError("");
          try {
            await browserApi().POST("/api/auth/admin/login", {
              body: {
                email: text(data, "email"),
                password: String(data.get("password") ?? ""),
                code: text(data, "code"),
              },
            });
            await navigate("/admin/customers", { replace: true });
          } catch (error) {
            setError(
              error instanceof ApiError && error.status === 401
                ? "Неверный email, пароль или одноразовый код."
                : message(error),
            );
          } finally {
            locked.current = false;
            setBusy(false);
          }
        }}
      >
        <Field
          label="Email администратора"
          name="email"
          type="email"
          autoComplete="username"
          required
          maxLength={320}
        />
        <Field
          label="Пароль"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          maxLength={128}
        />
        <Field
          label="Одноразовый код"
          name="code"
          inputMode="numeric"
          pattern="[0-9]{6}"
          autoComplete="one-time-code"
          required
          minLength={6}
          maxLength={6}
        />
        <Button type="submit">{busy ? "Вход…" : "Войти"}</Button>
      </Form>
    </div>
  );
}
