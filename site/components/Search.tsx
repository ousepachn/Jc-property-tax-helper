"use client";

// Address search. A condo building shows as one result; choosing it lists its units, and typing a unit
// number narrows them ("77 Hudson St 1205", "77 Hudson St, Unit 12", "#12" all work).
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import type { SearchHit } from "@/lib/types";
import { addressLine, kindLabel, unitLabel } from "@/lib/format";

export default function Search({ autoFocus = false, large = false }: { autoFocus?: boolean; large?: boolean }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [active, setActive] = useState(0);
  const router = useRouter();
  const listId = useId();
  const input = useRef<HTMLInputElement>(null);
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
        .then((h: SearchHit[]) => {
          setHits(h);
          setActive(0);
        })
        .catch(() => {});
    }, 140);
    return () => {
      clearTimeout(timer.current);
      ctrl.abort();
    };
  }, [q]);

  const choose = (h: SearchHit) => {
    if (h.units) {
      // a building: list its units, ready for the unit number
      setQ(`${addressLine(h.address, null)}, Unit `);
      input.current?.focus();
    } else {
      router.push(`/p/${h.pin}`);
    }
  };

  const unitMode = /(,|#|\bunit\b|\bapt\b)/i.test(q);
  const units = hits?.filter((h) => h.unit).length ?? 0;

  return (
    <div className={`search${large ? " lg" : ""}`} role="search">
      <label htmlFor="address" className="small muted" style={{ position: "absolute", left: -9999 }}>
        Find a property by address
      </label>
      <input
        id="address"
        ref={input}
        autoFocus={autoFocus}
        autoComplete="off"
        spellCheck={false}
        placeholder="Search an address, e.g. 280 Grove St"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (!hits?.length) return;
          if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, hits.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
          else if (e.key === "Enter") { e.preventDefault(); choose(hits[active] ?? hits[0]); }
          else if (e.key === "Escape") setHits(null);
        }}
        role="combobox"
        aria-controls={listId}
        aria-expanded={!!hits}
        aria-activedescendant={hits?.length ? `${listId}-${active}` : undefined}
      />
      {hits && (
        <ul className="results" id={listId} role="listbox">
          {hits.length === 0 && (
            <li className="none">
              {unitMode ? "No unit at that address matches. Check the unit number, or remove it to see the building." :
                "No Jersey City property matches. Try just the number and street, like “280 Grove”."}
            </li>
          )}
          {hits.map((h, i) => (
            <li key={h.pin || h.address} id={`${listId}-${i}`} role="option" aria-selected={i === active}>
              <button type="button" onClick={() => choose(h)} onMouseEnter={() => setActive(i)} tabIndex={-1}>
                <span>
                  {addressLine(h.address, null)}
                  {h.unit && <b>{`, ${unitLabel(h.unit)}`}</b>}
                </span>
                <span className="small muted">{h.units ? `${h.units.toLocaleString("en-US")} units →` : kindLabel(h.kind)}</span>
              </button>
            </li>
          ))}
          {unitMode && units >= 10 && <li className="tip">Type your unit number to narrow the list.</li>}
        </ul>
      )}
    </div>
  );
}
