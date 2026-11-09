// Loaded by cms.spec.cjs; all mutations use the runner's disposable CMS only.
const { test, expect, config, cms } = require("./helpers.cjs");
const uid = "api::footer-settings.footer-settings";
const empty = { data: { documents: [], usefulLinks: [] } };
const paragraph = [
  {
    type: "paragraph",
    children: [{ type: "text", text: "Synthetic footer test" }],
  },
];
const origin = `http://localhost:${config.ports.cms}`;
const endpoint = `${origin}/api/public-content/footer`;

async function publicFooter(request) {
  const response = await request.get(
    `${endpoint}?status=draft&populate=*&limit=1`,
  );
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toBe("no-store");
  return response.json();
}

test("footer API: publication, 50 ordered links, current slugs, unpublish, unlink, deletion and safe fields", async ({
  request,
}) => {
  expect(await publicFooter(request)).toEqual(empty);
  const documents = [];
  for (let i = 0; i < 50; i++) {
    const doc = await cms({
      action: "create",
      kind: "documents",
      data: {
        title: `Footer document ${i}`,
        slug: `footer-document-${i}`,
        body: paragraph,
        revisedOn: "2026-11-06",
      },
    });
    documents.push(doc);
    await cms({ action: "publish", kind: "documents", id: doc.documentId });
  }
  const usefulLinks = documents.map((doc, i) => ({
    label: `<b>Footer useful ${i}</b>`,
    href: i % 2 ? `/about?i=${i}` : `https://example.org/${i}`,
  }));
  const draftOnly = await cms({
    action: "create",
    kind: "documents",
    data: {
      title: "Footer unpublished document",
      slug: "footer-unpublished",
      body: paragraph,
      revisedOn: "2026-11-06",
    },
  });
  const ids = [
    ...documents.map((doc) => doc.documentId).reverse(),
    draftOnly.documentId,
  ];
  const footer = await cms({
    action: "create",
    kind: "footer",
    data: { documents: { set: ids }, usefulLinks },
  });
  expect(await publicFooter(request)).toEqual(empty);
  await cms({ action: "publish", kind: "footer", id: footer.documentId });
  const expected = documents
    .map((doc, i) => ({
      label: `Footer document ${i}`,
      href: `/documents/footer-document-${i}`,
    }))
    .reverse();
  expect(await publicFooter(request)).toEqual({
    data: { documents: expected, usefulLinks },
  });
  await cms({
    action: "update",
    kind: "documents",
    id: documents[20].documentId,
    data: { title: "Footer current title", slug: "footer-current-slug" },
  });
  expect((await publicFooter(request)).data.documents[29]).toEqual(
    expected[29],
  );
  await cms({
    action: "publish",
    kind: "documents",
    id: documents[20].documentId,
  });
  expected[29] = {
    label: "Footer current title",
    href: "/documents/footer-current-slug",
  };
  expect((await publicFooter(request)).data.documents).toEqual(expected);
  await cms({
    action: "unpublish",
    kind: "documents",
    id: documents[19].documentId,
  });
  await cms({
    action: "delete",
    kind: "documents",
    id: documents[18].documentId,
  });
  expect((await publicFooter(request)).data.documents).toEqual(
    expected.filter(
      (link) =>
        ![
          "/documents/footer-document-19",
          "/documents/footer-document-18",
        ].includes(link.href),
    ),
  );
  await cms({
    action: "update",
    kind: "footer",
    id: footer.documentId,
    data: {
      documents: {
        set: [
          documents[2].documentId,
          documents[0].documentId,
          documents[1].documentId,
        ],
      },
      usefulLinks: [],
    },
  });
  expect((await publicFooter(request)).data.usefulLinks).toEqual(usefulLinks);
  await cms({ action: "publish", kind: "footer", id: footer.documentId });
  expect(await publicFooter(request)).toEqual({
    data: {
      documents: [2, 0, 1].map((i) => ({
        label: `Footer document ${i}`,
        href: `/documents/footer-document-${i}`,
      })),
      usefulLinks: [],
    },
  });
  expect(
    await cms({
      action: "find",
      kind: "documents",
      slug: "footer-document-49",
    }),
  ).toHaveLength(1);
  for (const method of ["POST", "PUT", "DELETE"]) {
    expect((await request.fetch(endpoint, { method, data: {} })).status()).toBe(
      405,
    );
  }
  expect((await request.get(`${endpoint}/anything`)).status()).toBe(404);
  expect((await request.get(`${origin}/api/footer-settings`)).status()).toBe(
    404,
  );
});

test("footer Content Manager adds, edits, reorders, validates and publishes links without deleting documents", async ({
  page,
  request,
}) => {
  page.setDefaultTimeout(10000);
  const [footer] = await cms({ action: "find", kind: "footer" });
  await page.route("**/*", (route) =>
    ["localhost", "127.0.0.1"].includes(new URL(route.request().url()).hostname)
      ? route.continue()
      : route.abort(),
  );
  await page.goto(`${origin}/admin`);
  await expect(page.locator('input[name="email"]')).toBeVisible();
  const registration = await page
    .locator('input[name="firstname"]')
    .isVisible();
  if (registration) {
    await page.locator('input[name="firstname"]').fill("Footer");
    await page.locator('input[name="lastname"]').fill("Regression");
  }
  await page.locator('input[name="email"]').fill("cms-editor@example.org");
  await page
    .locator('input[name="password"]')
    .fill(`Aa1!${config.admin.password}`);
  if (registration)
    await page
      .locator('input[name="confirmPassword"]')
      .fill(`Aa1!${config.admin.password}`);
  await page
    .getByRole("button", {
      name: registration ? "Let's start" : "Login",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("link", { name: "Content Manager", exact: true }),
  ).toBeVisible();
  await page.goto(`${origin}/admin/content-manager/single-types/${uid}`);
  const rows = page
    .locator("li")
    .filter({ has: page.getByRole("button", { name: "Drag", exact: true }) });
  await expect(rows).toHaveCount(3);
  await page
    .getByRole("button", {
      name: "No entry yet. Click to add one.",
      exact: true,
    })
    .click();
  await page
    .locator('input[name="usefulLinks.0.label"]')
    .fill("Footer UI first");
  await page
    .locator('input[name="usefulLinks.0.href"]')
    .fill("javascript:alert(1)");
  async function save(status = 200) {
    const [response] = await Promise.all([
      page.waitForResponse(
        (r) =>
          r.request().method() === "PUT" &&
          r.url().includes(`/single-types/${uid}`),
      ),
      page.getByRole("button", { name: "Save", exact: true }).click(),
    ]);
    expect(response.status()).toBe(status);
    if (status === 200)
      await expect(
        page.getByRole("button", { name: "Save", exact: true }),
      ).toBeDisabled();
  }
  await save(400);
  expect((await publicFooter(request)).data.usefulLinks).toEqual([]);
  // Content Manager invalidates/refetches the draft after a failed mutation,
  // restoring the last saved state. Start valid editing after that reset.
  await expect(
    page.getByRole("button", {
      name: "No entry yet. Click to add one.",
      exact: true,
    }),
  ).toBeVisible();
  await rows.nth(2).getByRole("button", { name: "Drag", exact: true }).focus();
  await page.keyboard.press("Space");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("Space");
  await expect(rows.nth(0)).toContainText("Footer document 1");
  await rows
    .nth(2)
    .getByRole("button", { name: "Remove", exact: true })
    .click();

  await page.getByRole("combobox").fill("Footer document 3");
  await page.getByRole("combobox").press("ArrowDown");
  await page
    .getByRole("option")
    .filter({ has: page.getByText("Footer document 3", { exact: true }) })
    .click();
  await expect(rows).toHaveCount(3);
  await page
    .getByRole("button", {
      name: "No entry yet. Click to add one.",
      exact: true,
    })
    .click();
  await page
    .locator('input[name="usefulLinks.0.label"]')
    .fill("Footer UI first");
  await page.locator('input[name="usefulLinks.0.href"]').fill("/about");
  await page.getByRole("button", { name: "Add an entry", exact: true }).click();
  await page
    .locator('input[name="usefulLinks.1.label"]')
    .fill("Footer UI second");
  await page
    .locator('input[name="usefulLinks.1.href"]')
    .fill("https://example.org/second");
  await save();
  expect((await publicFooter(request)).data.usefulLinks).toEqual([]);
  async function publish() {
    const [response] = await Promise.all([
      page.waitForResponse(
        (r) =>
          r.request().method() === "POST" &&
          r.url().includes(`/single-types/${uid}/actions/publish`),
      ),
      page.getByRole("button", { name: "Publish", exact: true }).click(),
    ]);
    expect(response.status()).toBe(200);
  }
  await publish();
  expect((await publicFooter(request)).data).toEqual({
    documents: [1, 2, 3].map((i) => ({
      label: `Footer document ${i}`,
      href: `/documents/footer-document-${i}`,
    })),
    usefulLinks: [
      { label: "Footer UI first", href: "/about" },
      { label: "Footer UI second", href: "https://example.org/second" },
    ],
  });
  await page.reload();
  await expect(rows.nth(0)).toContainText("Footer document 1");
  // Component drag handles are separate from the relation list's li elements.
  const handles = page.getByRole("button", { name: "Drag", exact: true });
  await expect(handles).toHaveCount(5);
  await handles.last().focus();
  await page.keyboard.press("Space");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("Space");
  await save();
  await publish();
  expect(
    (await publicFooter(request)).data.usefulLinks.map((link) => link.label),
  ).toEqual(["Footer UI second", "Footer UI first"]);
  if (!(await page.locator('input[name="usefulLinks.0.label"]').isVisible()))
    await page.getByRole("button", { name: /Footer UI second/ }).click();
  await page
    .locator('input[name="usefulLinks.0.label"]')
    .fill("Footer UI edited");
  await page
    .locator('input[name="usefulLinks.0.href"]')
    .fill("http://example.org/edited");
  await page
    .getByRole("button", { name: "Delete", exact: true })
    .last()
    .click();
  await save();
  await publish();
  expect((await publicFooter(request)).data.usefulLinks).toEqual([
    { label: "Footer UI edited", href: "http://example.org/edited" },
  ]);
  expect(
    await cms({ action: "find", kind: "documents", slug: "footer-document-0" }),
  ).toHaveLength(1);
  await cms({
    action: "update",
    kind: "footer",
    id: footer.documentId,
    data: { documents: { set: [] }, usefulLinks: [] },
  });
  await cms({ action: "publish", kind: "footer", id: footer.documentId });
  expect(await publicFooter(request)).toEqual(empty);
});
