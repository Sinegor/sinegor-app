import { withPublicMetadata } from "../../lib/seo";
import type { Route } from "./+types/service";
import { loadPage } from "../../lib/cms.server";
import { ContentPage, contentMeta } from "../../components/cms-content";
export async function loader({ params }: Route.LoaderArgs) {
  const data = await loadPage("services", params.slug);
  if (!data.content) throw new Response("Not Found", { status: 404 });
  return data;
}
const pageMeta = ({ data }: Route.MetaArgs) =>
  data?.content
    ? contentMeta(data.content)
    : [{ title: "Страница не найдена — SINEGOR LAB" }];
export const meta = (args: Route.MetaArgs) =>
  withPublicMetadata(args, pageMeta(args));

export default function Page({ loaderData }: Route.ComponentProps) {
  return <ContentPage content={loaderData.content!} />;
}
