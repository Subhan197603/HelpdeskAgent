import { useEffect, useId, useRef } from "react";

const SHORTCUT_GROUPS = [
  {
    label: "Navigate",
    shortcuts: [
      { description: "Open the analyst dashboard", keys: ["G", "D"] },
      { description: "Open My queues", keys: ["G", "Q"] },
      { description: "Open analyst Knowledge", keys: ["G", "K"] },
    ],
  },
  {
    label: "Focus",
    shortcuts: [
      { description: "Focus the visible search", keys: ["/"] },
      { description: "Focus the visible personal selector", keys: ["F"] },
      { description: "Focus the next visible ticket", keys: ["J"] },
      { description: "Focus the previous visible ticket", keys: ["K"] },
    ],
  },
  {
    label: "Help",
    shortcuts: [
      { description: "Open this shortcut guide", keys: ["?"] },
      { description: "Close help or cancel a pending chord", keys: ["Escape"] },
    ],
  },
] as const;

export function ShortcutHelpDialog({
  enabled,
  onClose,
  onEnabledChange,
  open,
}: {
  enabled: boolean;
  onClose: () => void;
  onEnabledChange: (enabled: boolean) => void;
  open: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) {
      if (typeof element.showModal === "function") element.showModal();
      else element.setAttribute("open", "");
      closeButton.current?.focus();
    } else if (!open && element.open) {
      if (typeof element.close === "function") element.close();
      else element.removeAttribute("open");
    }
  }, [open]);

  return (
    <dialog
      aria-describedby={descriptionId}
      aria-labelledby={titleId}
      className="shortcut-help-dialog"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      ref={dialog}
    >
      <h2 id={titleId}>Keyboard shortcuts</h2>
      <p id={descriptionId}>
        Shortcuts navigate or move focus only. They pause while you type and
        never submit or change a ticket. Keyboard shortcuts are currently
        {enabled ? " on." : " off."}
      </p>
      <div className="shortcut-help-groups">
        {SHORTCUT_GROUPS.map((group) => (
          <section
            aria-labelledby={`shortcut-${group.label}`}
            key={group.label}
          >
            <h3 id={`shortcut-${group.label}`}>{group.label}</h3>
            <ul>
              {group.shortcuts.map((shortcut) => (
                <li key={shortcut.description}>
                  <span aria-label={shortcut.keys.join(" then ")}>
                    {shortcut.keys.map((key) => (
                      <kbd key={key}>{key}</kbd>
                    ))}
                  </span>
                  <span>{shortcut.description}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      <div className="dialog-actions">
        <button
          aria-pressed={enabled}
          className="button secondary"
          onClick={() => {
            onEnabledChange(!enabled);
          }}
          type="button"
        >
          {enabled ? "Turn off shortcuts" : "Turn on shortcuts"}
        </button>
        <button
          className="button secondary"
          onClick={onClose}
          ref={closeButton}
          type="button"
        >
          Close
        </button>
      </div>
    </dialog>
  );
}
