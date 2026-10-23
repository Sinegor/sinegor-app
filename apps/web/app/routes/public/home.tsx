import { Card } from "../../components/ui";
import { LabArt } from "../../components/lab-art";
export const meta = () => [
  { title: "SINEGOR LAB" },
  {
    name: "description",
    content: "Анализ и техническая подготовка документов.",
  },
];
export default function Home() {
  return (
    <section className="home-intro">
      <p className="eyebrow">SINEGOR LAB</p>
      <h1>Анализ и техническая подготовка документов</h1>
      <LabArt className="home-art" />
      <Card title="Приложение в разработке">
        <p>
          Публичные страницы и описание услуг появятся после подготовки рабочих
          интерфейсов.
        </p>
      </Card>
    </section>
  );
}
