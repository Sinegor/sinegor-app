import { useEffect, useId, useState, type ReactNode } from "react";
import { useLocation } from "react-router";
import { Button, Modal } from "./ui";

export function MobileNavigation({
  title,
  label,
  children,
}: {
  title: string;
  label: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const location = useLocation();
  useEffect(() => {
    setOpen(false);
  }, [location.key]);
  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1024px)");
    function closeOnDesktop() {
      if (desktop.matches) setOpen(false);
    }
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, []);
  return (
    <div className="mobile-navigation">
      <Button
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(true)}
      >
        {title === "Разделы" ? "Разделы" : "Меню"}
      </Button>
      <Modal
        id={id}
        className="mobile-menu-dialog"
        open={open}
        title={title}
        onClose={() => setOpen(false)}
      >
        <div className="mobile-menu-content">{children}</div>
      </Modal>
    </div>
  );
}
