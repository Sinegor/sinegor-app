import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { ApiError, browserApi } from "../../lib/api/client";
import { message, value, type Models } from "../../lib/admin/api";
import { Button } from "../ui";

type Customer = Models["CustomerRead"];
const selectionRequired = "Выберите заказчика из списка.";
function label(customer: Customer) {
  return [customer.display_name, customer.email, customer.phone]
    .filter(Boolean)
    .join(" · ");
}

export function CustomerCombobox({ initial }: { initial: Customer | null }) {
  const id = useId();
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const version = useRef(0);
  const [selected, setSelected] = useState(initial);
  const [query, setQuery] = useState(initial ? label(initial) : "");
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [active, setActive] = useState(-1);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    input.current?.setCustomValidity(selected ? "" : selectionRequired);
  }, [selected, query]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const current = ++version.current;
    setLoading(true);
    setError("");
    setRows([]);
    setActive(-1);
    // Opening an existing selection shows the latest customers, not a search
    // for its display label. Typing always clears the selection first.
    const search = selected ? "" : query.trim();
    const timer = window.setTimeout(
      async () => {
        try {
          const found = await value(
            browserApi().GET("/api/admin/customers", {
              params: { query: { q: search, limit: 100 } },
              signal: controller.signal,
            }),
          );
          if (version.current === current && !controller.signal.aborted)
            setRows(found);
        } catch (cause) {
          if (version.current !== current || controller.signal.aborted) return;
          if (cause instanceof ApiError && cause.status === 401) {
            void navigate("/auth/admin", { replace: true });
          } else setError(message(cause));
        } finally {
          if (version.current === current && !controller.signal.aborted)
            setLoading(false);
        }
      },
      search ? 300 : 0,
    );
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [open, query, selected, retry, navigate]);

  useEffect(() => {
    if (active >= 0)
      document
        .getElementById(`${id}-option-${active}`)
        ?.scrollIntoView({ block: "nearest" });
  }, [active, id]);

  function close() {
    version.current++;
    setOpen(false);
    setActive(-1);
  }
  function choose(customer: Customer) {
    close();
    setSelected(customer);
    setQuery(label(customer));
    input.current?.setCustomValidity("");
    input.current?.focus({ preventScroll: true });
  }

  return (
    <div
      className="field customer-combobox"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) close();
      }}
    >
      <label htmlFor={id}>Заказчик</label>
      <input
        ref={input}
        id={id}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={`${id}-list`}
        aria-activedescendant={
          open && active >= 0 ? `${id}-option-${active}` : undefined
        }
        aria-describedby={`${id}-status`}
        autoComplete="off"
        maxLength={selected ? undefined : 320}
        required
        placeholder="Имя, email или телефон"
        value={query}
        onClick={() => setOpen(true)}
        onInvalid={(event) => {
          if (!selected)
            event.currentTarget.setCustomValidity(selectionRequired);
        }}
        onChange={(event) => {
          version.current++;
          setSelected(null);
          setQuery(event.target.value);
          setRows([]);
          setActive(-1);
          setError("");
          setLoading(true);
          setOpen(true);
          event.currentTarget.setCustomValidity(selectionRequired);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            if (open) {
              event.preventDefault();
              close();
            }
          } else if (["ArrowDown", "ArrowUp"].includes(event.key)) {
            event.preventDefault();
            if (!open) setOpen(true);
            else if (rows.length)
              setActive((index) =>
                event.key === "ArrowDown"
                  ? Math.min(index + 1, rows.length - 1)
                  : index < 0
                    ? rows.length - 1
                    : Math.max(index - 1, 0),
              );
          } else if (
            open &&
            ["Home", "End"].includes(event.key) &&
            rows.length
          ) {
            event.preventDefault();
            setActive(event.key === "Home" ? 0 : rows.length - 1);
          } else if (event.key === "Enter" && open) {
            event.preventDefault();
            if (active >= 0 && rows[active]) choose(rows[active]);
          } else if (event.key === "Tab") close();
        }}
      />
      <input type="hidden" name="customer_id" value={selected?.id ?? ""} />
      <span id={`${id}-status`} className="customer-combobox__status">
        {selected
          ? `Выбран заказчик: ${label(selected)}`
          : "Введите запрос или откройте список стрелкой вниз."}
      </span>
      {open && (
        <div className="customer-combobox__dropdown">
          {loading && <p role="status">Загрузка заказчиков…</p>}
          {error && (
            <>
              <p role="alert">{error}</p>
              <Button onClick={() => setRetry((current) => current + 1)}>
                Повторить поиск
              </Button>
            </>
          )}
          {!loading && !error && !rows.length && (
            <p role="status">Заказчики не найдены. Измените запрос.</p>
          )}
          <ul
            id={`${id}-list`}
            role="listbox"
            aria-label="Найденные заказчики"
            aria-busy={loading}
          >
            {rows.map((customer, index) => (
              <li key={customer.id} role="presentation">
                <button
                  id={`${id}-option-${index}`}
                  type="button"
                  role="option"
                  tabIndex={-1}
                  aria-selected={selected?.id === customer.id}
                  className={active === index ? "is-active" : undefined}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => choose(customer)}
                >
                  {selected?.id === customer.id && (
                    <span aria-hidden="true">✓ </span>
                  )}
                  {label(customer)}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
