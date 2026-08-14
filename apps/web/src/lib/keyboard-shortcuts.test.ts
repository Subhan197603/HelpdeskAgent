import { afterEach, describe, expect, it } from "vitest";

import {
  focusShortcutTarget,
  isTextEntryTarget,
  moveVisibleTicketRowFocus,
  shouldSuspendShortcut,
} from "./keyboard-shortcuts";

afterEach(() => {
  document.body.replaceChildren();
});

describe("analyst keyboard shortcut safeguards", () => {
  it("recognizes native and editable text-entry contexts", () => {
    const input = document.createElement("input");
    const textarea = document.createElement("textarea");
    const select = document.createElement("select");
    const editor = document.createElement("div");
    editor.setAttribute("contenteditable", "true");
    const button = document.createElement("button");

    expect(isTextEntryTarget(input)).toBe(true);
    expect(isTextEntryTarget(textarea)).toBe(true);
    expect(isTextEntryTarget(select)).toBe(true);
    expect(isTextEntryTarget(editor)).toBe(true);
    expect(isTextEntryTarget(button)).toBe(false);
  });

  it("does not intercept repeated, composed, or modifier shortcuts", () => {
    expect(
      shouldSuspendShortcut(new KeyboardEvent("keydown", { ctrlKey: true })),
    ).toBe(true);
    expect(
      shouldSuspendShortcut(new KeyboardEvent("keydown", { metaKey: true })),
    ).toBe(true);
    expect(
      shouldSuspendShortcut(new KeyboardEvent("keydown", { altKey: true })),
    ).toBe(true);
    expect(
      shouldSuspendShortcut(new KeyboardEvent("keydown", { repeat: true })),
    ).toBe(true);
    expect(
      shouldSuspendShortcut(
        new KeyboardEvent("keydown", { isComposing: true }),
      ),
    ).toBe(true);
    expect(
      shouldSuspendShortcut(new KeyboardEvent("keydown", { key: "j" })),
    ).toBe(false);
  });

  it("focuses only the first rendered contextual target", () => {
    document.body.innerHTML = `
      <form data-shortcut-target="search" hidden><input id="hidden-search"></form>
      <form data-shortcut-target="search"><input id="visible-search"></form>
      <select data-shortcut-target="personal" id="personal"><option>One</option></select>
    `;

    expect(focusShortcutTarget("search")).toBe(true);
    expect(document.activeElement).toBe(
      document.querySelector("#visible-search"),
    );
    expect(focusShortcutTarget("personal")).toBe(true);
    expect(document.activeElement).toBe(document.querySelector("#personal"));
  });

  it("moves focus between rendered ticket rows without wrapping or activation", () => {
    document.body.innerHTML = `
      <div data-shortcut-rows>
        <a class="ticket-list-item" href="/agent/tickets/ERP-1">ERP-1</a>
        <a class="ticket-list-item" href="/agent/tickets/ERP-2" hidden>ERP-2</a>
        <a class="ticket-list-item" href="/agent/tickets/ERP-3">ERP-3</a>
      </div>
    `;
    const first = document.querySelector<HTMLElement>("[href$='ERP-1']");
    const last = document.querySelector<HTMLElement>("[href$='ERP-3']");

    expect(moveVisibleTicketRowFocus(1)).toBe(true);
    expect(document.activeElement).toBe(first);
    expect(moveVisibleTicketRowFocus(1)).toBe(true);
    expect(document.activeElement).toBe(last);
    expect(moveVisibleTicketRowFocus(1)).toBe(true);
    expect(document.activeElement).toBe(last);
    expect(moveVisibleTicketRowFocus(-1)).toBe(true);
    expect(document.activeElement).toBe(first);
    expect(window.location.pathname).not.toContain("ERP-");
  });
});
