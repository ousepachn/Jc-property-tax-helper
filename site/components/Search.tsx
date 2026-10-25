"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import type { SearchHit } from "@/lib/types";
import { addressLine, kindLabel } from "@/lib/format";

export default function Search({ autoFocus = false }: { autoFocus?: boolean }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const router = useRouter();
  const listId = useId();
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    clearTimeout(timer.current);
    if (q.trim().length < 2) {
      setHits(null);
      return;
    }
    const ctrl = new AbortController();
    timer.current = setTimeout(() => {
      fetch(`/api/search?q=${encodeURIComponent(q)}`, { signal: ctrl.signal })
        .then((r) => r.json())
        .then(setHits)
        .catch(() => {});
    }, 150);
    return () => {
      clearTimeout(timer.current);
      ctrl.abort();
    };
  }, [q]);

  return (
    <div className="search" role="search">
      <label htmlFor="address" className="small muted" style={{ display: "block", marginBottom: 6 }}>
        Find your property
      </label>
      <input
        id="address"
        autoFocus={autoFocus}
        autoComplete="off"
        placeholder="Street address, e.g. 280 Grove St"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && hits?.[0]) router.push(`/p/${hits[0].pin}`);
        }}
        aria-controls={listId}
        aria-expanded={!!hits}
      />
      {hits && (
        <ul className="results" id={listId}>
          {hits.length === 0 && <li className="none">No Jersey City property matches that address.</li>}
          {hits.map((h) => (
            <li key={h.pin}>
              <Link href={`/p/${h.pin}`}>
                <span>{addressLine(h.address, h.unit)}</span>
                <span className="small muted">{kindLabel(h.kind)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
