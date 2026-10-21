import { Card } from "../../components/ui";
export const meta = () => [
  { title: "SINEGOR" },
  {
    name: "description",
    content: "Анализ и техническая подготовка документов.",
  },
];
export default function Home() {
  return (
    <>
      <p className="eyebrow">SINEGOR</p>
      <h1>Анализ и техническая подготовка документов</h1>
      <Card title="Приложение в разработке">
        <p>
          Публичные страницы и описание услуг появятся после подготовки рабочих
          интерфейсов.
        </p>
      </Card>
    </>
  );
}
