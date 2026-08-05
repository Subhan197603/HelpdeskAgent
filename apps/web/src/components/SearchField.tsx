import { Icon } from "./Icon";

export function SearchField({
  className = "global-search",
  disabled,
  hint,
  label,
  onChange,
  placeholder,
  title,
  value,
  withIcon = true,
}: {
  className?: string;
  disabled?: boolean;
  hint?: string;
  label: string;
  onChange?: (value: string) => void;
  placeholder: string;
  title?: string;
  value?: string;
  withIcon?: boolean;
}) {
  return (
    <label className={className}>
      {withIcon && <Icon name="search" />}
      <input
        aria-label={label}
        disabled={disabled}
        onChange={
          onChange === undefined
            ? undefined
            : (event) => {
                onChange(event.target.value);
              }
        }
        placeholder={placeholder}
        title={title}
        value={value}
      />
      {hint !== undefined && <kbd aria-hidden="true">{hint}</kbd>}
    </label>
  );
}
