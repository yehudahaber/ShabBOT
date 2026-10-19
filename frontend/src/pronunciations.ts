/** Whole-word, case-insensitive respelling. Longer phrases win. Mirrors core/pronounce.py. */

export function applyPronunciation(text: string, mapping: Record<string, string> | undefined): string {
  if (!text || !mapping) return text;
  const items = Object.entries(mapping)
    .map(([word, says]) => [word.trim(), says.trim()] as const)
    .filter(([word, says]) => word && says)
    .sort((a, b) => b[0].length - a[0].length);
  let spoken = text;
  for (const [word, says] of items) {
    const parts = word.split(/\s+/).map(escapeRegExp);
    spoken = spoken.replace(new RegExp(`(?<!\\w)${parts.join("\\s+")}(?!\\w)`, "gi"), () => says);
  }
  return spoken;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
