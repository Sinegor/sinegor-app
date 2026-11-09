// Integration of the 22.2 contract with the built SSR; disposable CMS only.
const { test, expect, cms, runtimeErrors, config } = require("./helpers.cjs");
const body = [
  {
    type: "paragraph",
    children: [{ type: "text", text: "Synthetic footer SSR content" }],
  },
];
const footerHtml = (html) =>
  html.match(/<footer\b[^>]*>[\s\S]*?<\/footer>/)?.[0] || "";

test("published footer updates in SSR and same-section client navigation without rebuilding", async ({
  request,
  page,
  browser,
}) => {
  const [footer] = await cms({ action: "find", kind: "footer" });
  const documents = [];
  for (const name of ["one", "two"]) {
    const doc = await cms({
      action: "create",
      kind: "documents",
      data: {
        title: `SSR document ${name}`,
        slug: `footer-ssr-${name}`,
        body,
        revisedOn: "2026-11-06",
      },
    });
    documents.push(doc);
    await cms({ action: "publish", kind: "documents", id: doc.documentId });
    const content = await cms({
      action: "create",
      kind: "pages",
      data: {
        title: `SSR page ${name}`,
        slug: `footer-ssr-${name}`,
        sections: [],
      },
    });
    await cms({ action: "publish", kind: "pages", id: content.documentId });
  }
  const usefulLinks = [
    { label: "SSR next document", href: "/documents/footer-ssr-two" },
    { label: "SSR first page", href: "/pages/footer-ssr-one" },
    { label: "SSR next page", href: "/pages/footer-ssr-two" },
  ];
  const update = async (label, publish = true) => {
    await cms({
      action: "update",
      kind: "footer",
      id: footer.documentId,
      data: {
        documents: { set: documents.map((doc) => doc.documentId) },
        usefulLinks: [
          ...usefulLinks,
          { label, href: "https://example.org/footer-ssr" },
        ],
      },
    });
    if (publish)
      await cms({ action: "publish", kind: "footer", id: footer.documentId });
  };
  await update("SSR published first");
  const html = async (path) => {
    const response = await request.get(path);
    expect(response.status()).toBe(200);
    return footerHtml(await response.text());
  };
  for (const path of [
    "/",
    "/about",
    "/documents",
    "/documents/footer-ssr-one",
    "/pages/footer-ssr-one",
    "/auth/login",
  ]) {
    const text = await html(path);
    expect(text).toContain("SSR published first");
    expect(text).toContain('href="/documents/footer-ssr-one"');
    expect(text).not.toContain("/documents/privacy-policy");
  }
  await update("SSR draft stays private", false);
  expect(await html("/documents")).toContain("SSR published first");
  expect(await html("/documents")).not.toContain("SSR draft stays private");
  await update("SSR published second");
  expect(await html("/documents")).toContain("SSR published second");
  const errors = runtimeErrors(page);
  const requests = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.goto("/documents");
  const mainDocument = () =>
    page
      .locator("main")
      .getByRole("link", { name: "SSR document one", exact: true });
  await update("SSR after catalogue navigation");
  await mainDocument().click();
  await expect(page).toHaveURL(/\/documents\/footer-ssr-one$/);
  const navigation = page.getByRole("contentinfo");
  await expect(navigation).toContainText("SSR after catalogue navigation");
  await update("SSR after document navigation");
  await navigation
    .getByRole("link", { name: "SSR next document", exact: true })
    .click();
  await expect(page).toHaveURL(/\/documents\/footer-ssr-two$/);
  await expect(navigation).toContainText("SSR after document navigation");
  await navigation
    .getByRole("link", { name: "SSR first page", exact: true })
    .click();
  await update("SSR after page navigation");
  await navigation
    .getByRole("link", { name: "SSR next page", exact: true })
    .click();
  await expect(page).toHaveURL(/\/pages\/footer-ssr-two$/);
  await expect(navigation).toContainText("SSR after page navigation");
  expect(requests.some((url) => url.includes("/api/public-content/"))).toBe(
    false,
  );
  expect(errors).toEqual([]);

  // A document's published title/slug changes independently of footer settings.
  await cms({
    action: "update",
    kind: "documents",
    id: documents[0].documentId,
    data: { title: "SSR current document", slug: "footer-ssr-current" },
  });
  await cms({
    action: "publish",
    kind: "documents",
    id: documents[0].documentId,
  });
  const current = await html("/documents");
  expect(current).toContain('href="/documents/footer-ssr-current"');
  expect(current).toContain("SSR current document");
  expect(current).not.toContain('href="/documents/footer-ssr-one"');

  const nojs = await browser.newContext({
    javaScriptEnabled: false,
    baseURL: config.origin,
  });
  try {
    const plain = await nojs.newPage();
    await plain.goto("/pages/footer-ssr-one");
    await expect(plain.getByRole("contentinfo")).toContainText(
      "SSR after page navigation",
    );
    await expect(
      plain
        .getByRole("contentinfo")
        .getByRole("link", { name: "SSR current document", exact: true }),
    ).toHaveAttribute("href", "/documents/footer-ssr-current");
  } finally {
    await nojs.close();
  }

  // Reordering and editing a useful link must reach SSR in the same build.
  const changedLinks = [
    { label: "SSR renamed useful link", href: "https://example.org/changed" },
    ...usefulLinks.toReversed(),
  ];
  await cms({
    action: "update",
    kind: "footer",
    id: footer.documentId,
    data: {
      documents: { set: documents.toReversed().map((doc) => doc.documentId) },
      usefulLinks: changedLinks,
    },
  });
  const draft = await html("/auth/login");
  expect(draft).toContain("SSR after page navigation");
  expect(draft).not.toContain("SSR renamed useful link");
  await cms({ action: "publish", kind: "footer", id: footer.documentId });
  const reordered = await html("/auth/login");
  expect(reordered.indexOf('href="/documents/footer-ssr-two"')).toBeGreaterThan(
    -1,
  );
  expect(
    reordered.indexOf('href="/documents/footer-ssr-current"'),
  ).toBeGreaterThan(reordered.indexOf('href="/documents/footer-ssr-two"'));
  expect(reordered).toContain('href="https://example.org/changed"');
  expect(reordered).toContain("SSR renamed useful link");
  expect(reordered).not.toContain("https://example.org/footer-ssr");
  const usefulHtml =
    reordered.match(
      /<nav\b[^>]*aria-labelledby="footer-useful-title"[^>]*>[\s\S]*?<\/nav>/,
    )?.[0] || "";
  expect(usefulHtml).toContain("SSR renamed useful link");
  let previous = -1;
  for (const link of changedLinks) {
    const position = usefulHtml.indexOf(`href="${link.href}"`);
    expect(position).toBeGreaterThan(previous);
    previous = position;
  }
  await cms({
    action: "update",
    kind: "footer",
    id: footer.documentId,
    data: { documents: { set: [] }, usefulLinks: [] },
  });
  await cms({ action: "publish", kind: "footer", id: footer.documentId });
  const cleared = await html("/documents");
  expect(cleared).not.toMatch(/<a\b/);
  expect((await request.get("/documents/footer-ssr-current")).status()).toBe(
    200,
  );
});
