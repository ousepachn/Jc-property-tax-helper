"use client";

// What finished work could add to the yearly tax: value added x the city's assessment level x the rate.
import { useState } from "react";

export default function TaxImpact({ ratio, rate, year }: { ratio: number; rate: number; year: number }) {
  const [value, setValue] = useState("50000");
  const v = Number(value.replace(/[^\d.]/g, "")) || 0;
  const assessed = v * ratio, yearly = (assessed * rate) / 100;
  const m = (x: number) => x.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  return (
    <div className="calc">
      <label>
        Value the work adds to the property
        <input inputMode="numeric" value={value} onChange={(e) => setValue(e.target.value)} aria-describedby="calc-out" />
      </label>
      <p id="calc-out" aria-live="polite">
        About <b className="num">{m(assessed)}</b> more assessed value, so about <b className="num">{m(yearly)}</b> more tax a
        year at the {year} rate. The first added bill covers only the months after the work is finished.
      </p>
      <p className="small muted">
        Jersey City assesses at about {(ratio * 100).toFixed(1)}% of market value; the {year} rate is ${rate.toFixed(3)} per
        $100 of assessment. The added value is the assessor&apos;s estimate, which can differ from what the work cost.
      </p>
    </div>
  );
}
