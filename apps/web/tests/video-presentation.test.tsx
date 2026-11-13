import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { VideoPresentation } from "../app/components/video-presentation";

it.each([undefined, "", "   "])(
  "keeps the presentation layout without a media source for %j",
  (src) => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <VideoPresentation src={src} />
      </MemoryRouter>,
    );
    expect(html).toContain('class="hero-video"');
    expect(html).toContain("poster=");
    expect(html).toContain("Видеопрезентация пока недоступна");
    expect(html).not.toContain("<source");
    expect(html).not.toContain("controls=");
    expect(html).not.toContain(".mp4");
    expect(html).not.toContain("Скачать ролик");
  },
);

it("renders the CMS source, MIME type, poster and caption in SSR", () => {
  const html = renderToStaticMarkup(
    <MemoryRouter>
      <VideoPresentation
        src="http://localhost:1337/uploads/presentation.webm"
        type="video/webm"
        poster="http://localhost:1337/uploads/poster.jpg"
        caption="Презентация из CMS"
      />
    </MemoryRouter>,
  );
  expect(html).toContain(
    '<source src="http://localhost:1337/uploads/presentation.webm" type="video/webm"',
  );
  expect(html).toContain('poster="http://localhost:1337/uploads/poster.jpg"');
  expect(html).toContain("Презентация из CMS");
  expect(html).toContain('controls=""');
  expect(html).toContain('playsInline=""');
  expect(html).not.toContain("Видеопрезентация пока недоступна");
});
