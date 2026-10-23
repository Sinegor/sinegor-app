import { Consultation } from "../../components/consultation";
import { publicMeta } from "../../components/public-content";
export const meta = () =>
  publicMeta("Контакты", "Запрос предварительной консультации в SINEGOR LAB.");
export default function Contacts() {
  return (
    <div className="public-page public-prose">
      <p className="eyebrow">Связаться</p>
      <h1>Контакты</h1>
      <p>IT-лаборатория адвоката Артемьева Д. В.</p>
      <p>Для связи с исполнителем оставьте запрос на консультацию.</p>
      <Consultation />
    </div>
  );
}
