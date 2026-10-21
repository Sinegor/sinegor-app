import { SessionStatus } from "../../components/session-status";
export const meta = () => [{ title: "Личный кабинет — SINEGOR" }];
export default function CustomerHome() {
  return (
    <>
      <h1>Личный кабинет</h1>
      <SessionStatus role="customer" />
      <p>Интерфейс заказов появится на этапе F3.</p>
    </>
  );
}
