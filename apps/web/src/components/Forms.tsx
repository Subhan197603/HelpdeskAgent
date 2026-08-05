import {
  useEffect,
  useId,
  useRef,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

import { Button } from "./Button";

interface FieldProps {
  children: ReactNode;
  description?: string;
  error?: string;
  id: string;
  label: string;
  required?: boolean;
}

export function FormField({
  children,
  description,
  error,
  id,
  label,
  required,
}: FieldProps) {
  return (
    <div className={`form-field${error ? " form-field--error" : ""}`}>
      <label htmlFor={id}>
        {label}
        {required && <span aria-hidden="true"> *</span>}
      </label>
      {description && <p id={`${id}-description`}>{description}</p>}
      {children}
      {error && (
        <p className="field-error" id={`${id}-error`}>
          {error}
        </p>
      )}
    </div>
  );
}

export function TextInput({
  label,
  description,
  error,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & Omit<FieldProps, "children">) {
  return (
    <FormField
      description={description}
      error={error}
      id={props.id}
      label={label}
      required={props.required}
    >
      <input
        {...props}
        aria-describedby={
          [
            description && `${props.id}-description`,
            error && `${props.id}-error`,
          ]
            .filter(Boolean)
            .join(" ") || undefined
        }
        aria-invalid={Boolean(error)}
      />
    </FormField>
  );
}

export function TextArea({
  label,
  description,
  error,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & Omit<FieldProps, "children">) {
  return (
    <FormField
      description={description}
      error={error}
      id={props.id}
      label={label}
      required={props.required}
    >
      <textarea
        {...props}
        aria-describedby={
          [
            description && `${props.id}-description`,
            error && `${props.id}-error`,
          ]
            .filter(Boolean)
            .join(" ") || undefined
        }
        aria-invalid={Boolean(error)}
      />
    </FormField>
  );
}

export function Select({
  label,
  description,
  error,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> &
  Omit<FieldProps, "children"> & { children: ReactNode }) {
  return (
    <FormField
      description={description}
      error={error}
      id={props.id}
      label={label}
      required={props.required}
    >
      <select
        {...props}
        aria-describedby={
          [
            description && `${props.id}-description`,
            error && `${props.id}-error`,
          ]
            .filter(Boolean)
            .join(" ") || undefined
        }
        aria-invalid={Boolean(error)}
      >
        {children}
      </select>
    </FormField>
  );
}

export function MultiSelect(
  props: SelectHTMLAttributes<HTMLSelectElement> &
    Omit<FieldProps, "children"> & { children: ReactNode },
) {
  return <Select {...props} multiple />;
}

export function Checkbox({
  label,
  description,
  error,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & Omit<FieldProps, "children">) {
  return (
    <FormField
      description={description}
      error={error}
      id={props.id}
      label={label}
      required={props.required}
    >
      <input {...props} type="checkbox" />
    </FormField>
  );
}

export function DateInput(
  props: InputHTMLAttributes<HTMLInputElement> &
    Omit<FieldProps, "children" | "type">,
) {
  return <TextInput {...props} type="date" />;
}

export function DateTimeInput(
  props: InputHTMLAttributes<HTMLInputElement> &
    Omit<FieldProps, "children" | "type">,
) {
  return <TextInput {...props} type="datetime-local" />;
}

export function SubmissionReview({
  actions,
  children,
  title = "Review your request",
}: {
  actions?: ReactNode;
  children: ReactNode;
  title?: string;
}) {
  return (
    <section
      className="submission-review"
      aria-labelledby="submission-review-title"
    >
      <h2 id="submission-review-title">{title}</h2>
      {children}
      {actions && <div className="dialog-actions">{actions}</div>}
    </section>
  );
}

export function ConfirmationDialog({
  cancelLabel = "Cancel",
  children,
  confirmLabel = "Confirm",
  onCancel,
  onConfirm,
  open,
  title,
}: {
  cancelLabel?: string;
  children: ReactNode;
  confirmLabel?: string;
  onCancel: () => void;
  onConfirm: () => void;
  open: boolean;
  title: string;
}) {
  const titleId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) {
      if (typeof element.showModal === "function") element.showModal();
      else element.setAttribute("open", "");
    }
    if (!open && element.open) {
      if (typeof element.close === "function") element.close();
      else element.removeAttribute("open");
    }
  }, [open]);
  return (
    <dialog
      aria-labelledby={titleId}
      className="confirmation-dialog"
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
      ref={dialog}
    >
      <h2 id={titleId}>{title}</h2>
      {children}
      <div className="dialog-actions">
        <Button onClick={onCancel} variant="secondary">
          {cancelLabel}
        </Button>
        <Button onClick={onConfirm}>{confirmLabel}</Button>
      </div>
    </dialog>
  );
}

export function FormErrorSummary({
  errors,
}: {
  errors: readonly { field: string; message: string }[];
}) {
  if (errors.length === 0) return null;
  return (
    <section className="error-summary" role="alert">
      <h2>Check the highlighted fields</h2>
      <ul>
        {errors.map((error) => (
          <li key={`${error.field}-${error.message}`}>
            <a href={`#${error.field}`}>{error.message}</a>
          </li>
        ))}
      </ul>
    </section>
  );
}
