import { useEffect } from "react";

export function usePrivateDocument() {
  useEffect(() => {
    const root = document.documentElement;
    // Hide before the browser freezes the document, so a restored snapshot
    // cannot expose old private data while a fresh session check is pending.
    const hide = () => {
      root.hidden = true;
    };
    const restore = (event: PageTransitionEvent) => {
      if (event.persisted) {
        hide();
        window.location.reload();
      }
    };
    window.addEventListener("pagehide", hide);
    window.addEventListener("pageshow", restore);
    return () => {
      window.removeEventListener("pagehide", hide);
      window.removeEventListener("pageshow", restore);
      root.hidden = false;
    };
  }, []);
}
