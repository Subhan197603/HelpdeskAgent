import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Icon, type IconName } from "./Icon";

type ButtonVariant = "danger" | "inverse" | "primary" | "secondary";

function variantClassName(variant: ButtonVariant): string {
  if (variant === "inverse") return "button secondary button--inverse";
  return `button ${variant}`;
}

export function Button({
  children,
  disabled,
  onClick,
  to,
  type = "button",
  variant = "primary",
}: {
  children: ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  to?: string;
  type?: "button" | "submit";
  variant?: ButtonVariant;
}) {
  const className = variantClassName(variant);
  if (to !== undefined)
    return (
      <Link className={className} onClick={onClick} to={to}>
        {children}
      </Link>
    );
  return (
    <button
      className={className}
      disabled={disabled}
      onClick={onClick}
      type={type}
    >
      {children}
    </button>
  );
}

export function IconButton({
  className,
  disabled,
  icon,
  label,
  onClick,
}: {
  className?: string;
  disabled?: boolean;
  icon: IconName;
  label: string;
  onClick?: () => void;
}) {
  return (
    <button
      aria-label={label}
      className={`icon-button${className ? ` ${className}` : ""}`}
      disabled={disabled}
      onClick={onClick}
      type="button"
    >
      <Icon name={icon} />
    </button>
  );
}
