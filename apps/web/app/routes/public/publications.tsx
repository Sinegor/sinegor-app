import {
  PublicationsPreview,
  publicMeta,
} from "../../components/public-content";
export const meta = () =>
  publicMeta(
    "Публикации",
    "Материалы SINEGOR LAB об исследовании и подготовке документов.",
  );
export default function Publications() {
  return (
    <section className="public-page">
      <p className="eyebrow">Материалы лаборатории</p>
      <h1>Публикации</h1>
      <PublicationsPreview />
    </section>
  );
}
