import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { browserApi, ApiError } from "../../lib/api/client";
import { takeMagicToken } from "../../lib/api/magic-link";
import { message } from "../../lib/admin/api";
import { Button, Notice } from "../../components/ui";
export const meta = () => [
  { title: "Подтверждение входа — SINEGOR" },
  { name: "robots", content: "noindex, nofollow" },
];
export default function MagicLink() {
  const token = useRef<string | null>(null),
    initialized = useRef(false),
    locked = useRef(false);
  const [ready, setReady] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const navigate = useNavigate(),
    location = useLocation();
  useEffect(() => {
    function consumeFragment() {
      if (
        initialized.current &&
        !new URLSearchParams(window.location.hash.slice(1)).has("token")
      )
        return;
      initialized.current = true;
      token.current = takeMagicToken(window.location, window.history);
      setReady(!!token.current);
      setError(
        token.current
          ? ""
          : "Ссылка недействительна. Запросите новую ссылку для входа.",
      );
    }
    consumeFragment();
    window.addEventListener("hashchange", consumeFragment);
    return () => window.removeEventListener("hashchange", consumeFragment);
  }, [location.key, location.hash]);
  async function confirm() {
    const candidate = token.current;
    if (!candidate || locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    try {
      await browserApi().POST("/api/auth/magic-link/verify", {
        body: { token: candidate },
      });
      if (token.current !== candidate) return;
      token.current = null;
      setReady(false);
      await navigate("/customer/orders", { replace: true });
    } catch (error) {
      if (token.current !== candidate) return;
      if (error instanceof ApiError && [401, 422].includes(error.status)) {
        token.current = null;
        setReady(false);
        setError(
          "Ссылка истекла или уже использована. Запросите новую ссылку для входа.",
        );
      } else
        setError(
          error instanceof ApiError && error.status === 403
            ? "Не удалось проверить защиту формы. Повторите подтверждение входа."
            : message(error),
        );
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  return (
    <div className="login">
      <h1>Подтверждение входа</h1>
      <p>Войти в личный кабинет по ссылке из письма?</p>
      {error && <Notice error>{error}</Notice>}
      <Button disabled={!ready || busy} onClick={confirm}>
        {busy ? "Вход…" : "Подтвердить вход"}
      </Button>
      <p>
        <Link to="/auth/login">Получить новую ссылку</Link>
      </p>
    </div>
  );
}
