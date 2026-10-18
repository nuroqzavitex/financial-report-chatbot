/** Display only: renders printed page numbers as a citation label. */
export function citationLabel(pages: number[]): string {
  return `[tr. ${pages.join(", ")}]`;
}
