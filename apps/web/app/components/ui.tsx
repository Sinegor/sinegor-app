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
  onInvalidCapture,
  onInputCapture,
  ...props
}: FormHTMLAttributes<HTMLFormElement> & { busy?: boolean; error?: string }) {
  return (
    <form
      {...props}
      aria-busy={busy}
      onInvalidCapture={(event) => {
        const field = event.target;
        if (
          field instanceof HTMLInputElement ||
          field instanceof HTMLTextAreaElement ||
          field instanceof HTMLSelectElement
        ) {
          if (!field.validity.customError)
            field.setCustomValidity(validationMessage(field));
        }
        onInvalidCapture?.(event);
      }}
      onInputCapture={(event) => {
        const field = event.target;
        if (
          field instanceof HTMLInputElement ||
          field instanceof HTMLTextAreaElement ||
          field instanceof HTMLSelectElement
        )
          field.setCustomValidity("");
        onInputCapture?.(event);
      }}
    >
      {error && <Notice error>{error}</Notice>}
      <fieldset disabled={busy}>{children}</fieldset>
    </form>
  );
}

function validationMessage(
  field: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement,
) {
  const validity = field.validity;
  if (validity.valueMissing) {
    if (field instanceof HTMLInputElement && field.type === "checkbox")
      return "Подтвердите это действие.";
    if (field instanceof HTMLSelectElement)
      return "Выберите значение из списка.";
    return "Заполните это поле.";
  }
  if (
    validity.typeMismatch &&
    field instanceof HTMLInputElement &&
    field.type === "email"
  )
    return "Укажите корректный email.";
  if (
    validity.typeMismatch &&
    field instanceof HTMLInputElement &&
    field.type === "url"
  )
    return "Укажите корректную ссылку.";
  if (validity.tooLong) return "Сократите текст до допустимой длины.";
  if (validity.tooShort) return "Введите текст необходимой длины.";
  if (validity.rangeUnderflow || validity.rangeOverflow)
    return "Укажите значение в допустимом диапазоне.";
  if (validity.stepMismatch || validity.badInput)
    return "Укажите корректное числовое значение.";
  return "Проверьте формат значения.";
}
