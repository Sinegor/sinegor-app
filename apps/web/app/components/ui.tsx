import {
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type FormHTMLAttributes,
  type ReactNode,
} from "react";

export function Button({
  children,
  variant,
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "text";
}) {
  return (
    <button
      type={type}
      className={`button button--${variant ?? (type === "submit" ? "primary" : "secondary")} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
export function Field({
  label,
  error,
  id,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }) {
  const generated = useId();
  const inputId = id ?? generated;
  return (
    <div className="field">
      <label htmlFor={inputId}>{label}</label>
      <input
        {...props}
        id={inputId}
        aria-invalid={!!error}
        aria-describedby={error ? `${inputId}-error` : undefined}
      />
      {error && (
        <span id={`${inputId}-error`} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
export function Card({
  title,
  children,
  className = "",
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}
export function Notice({
  children,
  error = false,
  tone = "info",
}: {
  children: ReactNode;
  error?: boolean;
  tone?: "info" | "success" | "warning";
}) {
  return (
    <div
      className={`notice${error ? " error" : ""}`}
      data-tone={error ? "error" : tone}
      role={error ? "alert" : "status"}
    >
      {children}
    </div>
  );
}
export function LoadingStatus({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`loading-status ${className}`} role="status">
      <span className="loading-spinner" aria-hidden="true" />
      <span>{children}</span>
    </div>
  );
}
export function Table({
  caption,
  columns,
  rows,
  emptyMessage = "Нет данных",
}: {
  caption: string;
  columns: string[];
  rows: ReactNode[][];
  emptyMessage?: ReactNode;
}) {
  return (
    <div
      className="table-scroll"
      tabIndex={0}
      role="region"
      aria-label={caption}
    >
      <table>
        <caption>{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th scope="col" key={column}>
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length ? (
            rows.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j}>{cell}</td>
                ))}
              </tr>
            ))
          ) : (
            <tr>
              <td className="table-empty" colSpan={columns.length}>
                {emptyMessage}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
export function Modal({
  open,
  title,
  children,
  onClose,
  busy = false,
  id: dialogId,
  className = "",
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  onClose: () => void;
  busy?: boolean;
  id?: string;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      headingRef.current?.focus();
    } else if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      id={dialogId}
      className={className}
      ref={ref}
      aria-labelledby={id}
      onCancel={(event) => {
        if (busy) event.preventDefault();
      }}
      onClose={onClose}
    >
      <h2 id={id} ref={headingRef} tabIndex={-1}>
        {title}
      </h2>
      {children}
      {busy && <LoadingStatus>Выполняется…</LoadingStatus>}
      <Button disabled={busy} onClick={() => ref.current?.close()}>
        Закрыть
      </Button>
    </dialog>
  );
}

export function Form({
  busy = false,
  error,
  children,
  ...props
}: FormHTMLAttributes<HTMLFormElement> & { busy?: boolean; error?: string }) {
  return (
    <form {...props} aria-busy={busy}>
      {error && <Notice error>{error}</Notice>}
      <fieldset disabled={busy}>{children}</fieldset>
    </form>
  );
}
