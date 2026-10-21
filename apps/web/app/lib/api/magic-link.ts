export function takeMagicToken(
  location: Pick<Location, "hash" | "pathname" | "search">,
  history: Pick<History, "replaceState" | "state">,
) {
  const token = new URLSearchParams(location.hash.slice(1)).get("token");
  history.replaceState(history.state, "", location.pathname + location.search);
  return token && /^[A-Za-z0-9_-]{43}$/.test(token) ? token : null;
}
