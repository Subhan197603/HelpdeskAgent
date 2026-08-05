import { Icon } from "./Icon";

export function SearchField({
  className = "global-search",
  disabled,
  hint,
  label,
  placeholder,
  title,
  withIcon = true,
}: {
  className?: string;
  disabled?: boolean;
  hint?: string;
  label: string;
  placeholder: string;
  title?: string;
  withIcon?: boolean;
}) {
  return (
    <label className={className}>
      {withIcon && <Icon name="search" />}
      <input
        aria-label={label}
        disabled={disabled}
        placeholder={placeholder}
        title={title}
      />
      {hint !== undefined && <kbd aria-hidden="true">{hint}</kbd>}
    </label>
  );
}
