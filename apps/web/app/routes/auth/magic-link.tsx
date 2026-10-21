import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { browserApi, ApiError } from "../../lib/api/client";
import { takeMagicToken } from "../../lib/api/magic-link";
import { Button, Notice } from "../../components/ui";
export const meta = () => [
  { title: "Подтверждение входа — SINEGOR" },
  { name: "robots", content: "noindex, nofollow" },
];
export default function MagicLink() {
  const token = useRef<string | null>(null);
  const initialized = useRef(false);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    token.current = takeMagicToken(window.location, window.history);
    setReady(!!token.current);
    if (!token.current)
      setError("Ссылка недействительна. Откройте новую ссылку из письма.");
  }, []);
  async function confirm() {
    if (!token.current || busy) return;
    setBusy(true);
    setError("");
    try {
      await browserApi().POST("/api/auth/magic-link/verify", {
        body: { token: token.current },
      });
      token.current = null;
      await navigate("/customer", { replace: true });
    } catch (error) {
      setError(
        error instanceof ApiError
          ? "Не удалось войти. Ссылка могла истечь или уже использована. Повторите попытку или запросите новую ссылку."
          : "Не удалось связаться с сервером. Повторите попытку.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <h1>Подтверждение входа</h1>
      <p>Войти в личный кабинет по ссылке из письма?</p>
      {error && <Notice error>{error}</Notice>}
      <Button disabled={!ready || busy} onClick={confirm}>
        {busy ? "Вход…" : "Подтвердить вход"}
      </Button>
    </>
  );
}
