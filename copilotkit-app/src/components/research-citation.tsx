"use client";

export function CitationText({ text, onSource }: { text: string; onSource: (id: string) => void }) {
  return <>{text.split(/(\[S\d+\])/g).map((part, i) => /^\[S\d+\]$/.test(part)
    ? <button key={i} className="citation" onClick={() => onSource(part.slice(1, -1))}>{part}</button> : part)}</>;
}
