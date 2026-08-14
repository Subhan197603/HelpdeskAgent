export type ShortcutFocusTarget = "personal" | "search";

const EDITABLE_SELECTOR = [
  "input",
  "textarea",
  "select",
  "[contenteditable='']",
  "[contenteditable='true']",
  "[role='combobox']",
  "[role='searchbox']",
  "[role='textbox']",
].join(",");

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

export function isTextEntryTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  const editableAncestor = target.closest("[contenteditable]");
  if (
    editableAncestor &&
    editableAncestor.getAttribute("contenteditable") !== "false"
  )
    return true;
  return target.closest(EDITABLE_SELECTOR) !== null;
}

export function shouldSuspendShortcut(event: KeyboardEvent): boolean {
  return (
    event.defaultPrevented ||
    event.repeat ||
    event.isComposing ||
    event.altKey ||
    event.ctrlKey ||
    event.metaKey ||
    isTextEntryTarget(event.target)
  );
}

export function isRendered(element: HTMLElement): boolean {
  if (element.hidden || element.getAttribute("aria-hidden") === "true")
    return false;
  let current: HTMLElement | null = element;
  while (current) {
    const style = window.getComputedStyle(current);
    if (style.display === "none" || style.visibility === "hidden") return false;
    current = current.parentElement;
  }
  return true;
}

function focusableTarget(element: HTMLElement): HTMLElement | null {
  if (element.matches(FOCUSABLE_SELECTOR)) return element;
  return element.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
}

export function focusShortcutTarget(
  target: ShortcutFocusTarget,
  root: ParentNode = document,
): boolean {
  const candidates = root.querySelectorAll<HTMLElement>(
    `[data-shortcut-target="${target}"]`,
  );
  for (const candidate of candidates) {
    const focusable = focusableTarget(candidate);
    if (!focusable || !isRendered(focusable)) continue;
    focusable.focus();
    return true;
  }
  return false;
}

export function moveVisibleTicketRowFocus(
  direction: -1 | 1,
  root: ParentNode = document,
): boolean {
  const rows = Array.from(
    root.querySelectorAll<HTMLElement>(
      "[data-shortcut-rows] .ticket-list-item",
    ),
  ).filter(isRendered);
  if (rows.length === 0) return false;

  const activeIndex = rows.findIndex((row) => row === document.activeElement);
  const nextIndex =
    activeIndex < 0
      ? direction === 1
        ? 0
        : rows.length - 1
      : Math.min(rows.length - 1, Math.max(0, activeIndex + direction));
  rows[nextIndex]?.focus();
  return true;
}
