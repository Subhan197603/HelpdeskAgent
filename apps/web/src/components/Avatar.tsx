const TONE_COUNT = 8;

function toneIndex(seed: string): number {
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) >>> 0;
  }
  return hash % TONE_COUNT;
}

function initialsOf(name: string): string {
  const parts = name.split(/\s+/).filter((part) => part.length > 0);
  const first = parts[0]?.charAt(0) ?? "?";
  const second = parts.length > 1 ? (parts[1]?.charAt(0) ?? "") : "";
  return (first + second).toUpperCase();
}

export function Avatar({
  name,
  seed,
  size = "md",
}: {
  name: string;
  seed?: string;
  size?: "md" | "sm";
}) {
  const tone = String(toneIndex(seed ?? name));
  return (
    <span
      aria-hidden="true"
      className={`avatar avatar--${size} avatar--tone-${tone}`}
    >
      {initialsOf(name)}
    </span>
  );
}
