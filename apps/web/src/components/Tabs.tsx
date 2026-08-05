import { useRef } from "react";

export interface TabItem {
  badge?: string;
  id: string;
  label: string;
}

export function Tabs({
  activeId,
  items,
  label,
  onChange,
}: {
  activeId: string;
  items: readonly TabItem[];
  label: string;
  onChange: (id: string) => void;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  const moveTo = (index: number) => {
    const item = items.at(
      ((index % items.length) + items.length) % items.length,
    );
    if (!item) return;
    onChange(item.id);
    const buttons =
      listRef.current?.querySelectorAll<HTMLButtonElement>("[role='tab']");
    buttons?.[((index % items.length) + items.length) % items.length]?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const current = items.findIndex((item) => item.id === activeId);
    if (event.key === "ArrowRight") moveTo(current + 1);
    else if (event.key === "ArrowLeft") moveTo(current - 1);
    else if (event.key === "Home") moveTo(0);
    else if (event.key === "End") moveTo(items.length - 1);
    else return;
    event.preventDefault();
  };

  return (
    <div
      aria-label={label}
      className="project-tabs"
      onKeyDown={onKeyDown}
      ref={listRef}
      role="tablist"
    >
      {items.map((item) => (
        <button
          aria-selected={item.id === activeId}
          className={item.id === activeId ? "active" : ""}
          key={item.id}
          onClick={() => {
            onChange(item.id);
          }}
          role="tab"
          tabIndex={item.id === activeId ? 0 : -1}
          type="button"
        >
          {item.badge !== undefined && <span>{item.badge}</span>}
          {item.label}
        </button>
      ))}
    </div>
  );
}
