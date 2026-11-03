import { useState } from "react";
import { createRoot } from "react-dom/client";
import { createMemoryRouter, Link, Outlet, RouterProvider } from "react-router";
import {
  PublicAnalytics,
  useAnalytics,
} from "../../../app/components/public-analytics";

function Player() {
  const record = useAnalytics();
  return (
    <button onClick={() => record("video_presentation_view")}>
      Начать просмотр
    </button>
  );
}

function Home() {
  const [version, setVersion] = useState(0);
  return (
    <>
      <Player key={version} />
      <button onClick={() => setVersion((value) => value + 1)}>
        Перемонтировать плеер
      </button>
      <Link to="/about">Другая страница</Link>
    </>
  );
}

const router = createMemoryRouter([
  {
    path: "/",
    element: (
      <PublicAnalytics counterId={12345678}>
        <Outlet />
      </PublicAnalytics>
    ),
    children: [
      {
        index: true,
        id: "routes/public/home",
        loader: () => ({}),
        element: <Home />,
      },
      {
        path: "about",
        id: "routes/public/about",
        loader: () => ({}),
        element: (
          <button onClick={() => router.navigate(-1)}>Вернуться назад</button>
        ),
      },
    ],
  },
]);
createRoot(document.getElementById("root")!).render(
  <RouterProvider router={router} />,
);
