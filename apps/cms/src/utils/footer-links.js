// Reject addresses the browser could normalize into a different protocol/host.
function isSafeFooterHref(href) {
  if (
    typeof href !== "string" ||
    !href ||
    /[\s\u0000-\u001f\u007f-\u009f\\]/u.test(href)
  )
    return false;
  if (href.startsWith("/")) return !href.startsWith("//");
  if (!/^https?:\/\//i.test(href)) return false;
  try {
    const url = new URL(href);
    return ["http:", "https:"].includes(url.protocol) && Boolean(url.hostname);
  } catch {
    return false;
  }
}
module.exports = { isSafeFooterHref };
