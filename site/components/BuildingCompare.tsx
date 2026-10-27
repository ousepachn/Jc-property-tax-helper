// A condo unit against the other units in its building: assessment per square foot, adjusted for floor.
import Link from "next/link";
import { money, pct, unitLabel } from "@/lib/format";
import type { BuildingCompare as BC } from "@/lib/types";

export default function BuildingCompare({ b, address }: { b: BC; address: string }) {
  const diff = b.vs_floor ?? b.vs_median;
  const basis = b.vs_floor != null ? "units on similar floors" : "the typical unit";
  return (
    <section className="card" aria-labelledby="h-building">
      <header>
        <span className="eyebrow">Your building</span>
        <h2 id="h-building">
          {Math.abs(diff) < 0.03 ? "Assessed in line with your building"
            : `Assessed ${pct(Math.abs(diff)).replace("+", "")} ${diff > 0 ? "above" : "below"} ${basis}`}
        </h2>
        <p className="small muted">
          Every unit at {address} by assessed value per square foot ({b.compared} of {b.units} units have a usable size
          {b.abated_units ? `; ${b.abated_units} are abated, and their full value, taxable plus exempt, is used` : ""}).
          Higher floors usually carry higher values, so units are compared with units on similar floors when the
          building has enough of them.
        </p>
      </header>
      <div className="stats">
        <div className="stat you"><span className="k">This unit</span><span className="v">{money(b.ppsf)}/sq ft</span></div>
        <div className="stat"><span className="k">Building median</span><span className="v">{money(b.median_ppsf)}/sq ft</span></div>
        <div className="stat"><span className="k">Assessed higher than</span><span className="v">{b.higher_than}%</span><span className="small muted">of units, per sq ft</span></div>
      </div>
      {b.above && (
        <p className="note">
          <b>Worth a look.</b> Assessments in one building should be consistent. If nothing about this unit (size, view,
          upgrades) explains the difference, ask the Tax Assessor about it; it can support an appeal.
        </p>
      )}
      <div className="tablewrap">
        <table>
          <thead><tr><th>Units like yours</th><th className="r">Floor</th><th className="r">Size</th><th className="r hide-sm">Assessed</th><th className="r">Per sq ft</th></tr></thead>
          <tbody>
            {b.list.map((u) => (
              <tr key={u.pin}>
                <td><Link href={`/p/${u.pin}`}>{unitLabel(u.unit)}</Link></td>
                <td className="r">{u.floor ?? "—"}</td>
                <td className="r">{u.sq_ft.toLocaleString("en-US")}</td>
                <td className="r hide-sm">{money(u.value)}</td>
                <td className="r">{money(u.ppsf)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
