import type { SVGProps } from "react";

export type IconName =
  | "activity"
  | "bell"
  | "book"
  | "catalog"
  | "chevron"
  | "close"
  | "help"
  | "home"
  | "menu"
  | "queue"
  | "search"
  | "settings"
  | "shield"
  | "ticket"
  | "user";

const paths: Record<IconName, string> = {
  activity: "M4 12h3l2-5 4 10 2-5h5",
  bell: "M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4",
  book: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z",
  catalog: "M4 5h16v14H4zM4 10h16M9 5v14",
  chevron: "m9 18 6-6-6-6",
  close: "M6 6l12 12M18 6 6 18",
  help: "M9.1 9a3 3 0 1 1 5.4 1.8c-1.6 1-2.5 1.4-2.5 3.2M12 18h.01M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20",
  home: "m3 11 9-8 9 8v9h-6v-6H9v6H3z",
  menu: "M4 7h16M4 12h16M4 17h16",
  queue: "M5 6h14M5 12h14M5 18h10",
  search: "m21 21-4.35-4.35M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  settings:
    "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.12 2.12-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.04 1.57V20.3h-3v-.07a1.7 1.7 0 0 0-1.04-1.57 1.7 1.7 0 0 0-1.88.34l-.06.06-2.12-2.12.06-.06A1.7 1.7 0 0 0 7 15a1.7 1.7 0 0 0-1.57-1.04H5.3v-3h.13A1.7 1.7 0 0 0 7 9.92a1.7 1.7 0 0 0-.34-1.88L6.6 8l2.12-2.12.06.06a1.7 1.7 0 0 0 1.88.34A1.7 1.7 0 0 0 11.7 4.7V4.6h3v.1a1.7 1.7 0 0 0 1.04 1.58 1.7 1.7 0 0 0 1.88-.34l.06-.06L19.8 8l-.06.04a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.57 1.04h.13v3h-.13A1.7 1.7 0 0 0 19.4 15",
  shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  ticket: "M4 5h16v5a2 2 0 0 0 0 4v5H4v-5a2 2 0 0 0 0-4zM9 8v8",
  user: "M20 21a8 8 0 0 0-16 0M12 13a5 5 0 1 0 0-10 5 5 0 0 0 0 10",
};

export function Icon({
  name,
  ...props
}: SVGProps<SVGSVGElement> & { name: IconName }) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      height="20"
      viewBox="0 0 24 24"
      width="20"
      {...props}
    >
      <path
        d={paths[name]}
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}
