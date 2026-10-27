// What an abatement means for this property: active (the charge replaces regular tax on the building,
// until when) or ended (why the tax jumped).
import { LAW, money, monthYear } from "@/lib/format";
import type { Property } from "@/lib/types";

export function abatementChip(p: Property) {
  const a = p.abatement;
  if (!a) return null;
  if (a.status === "ended") return `Abatement ended ${a.year}`;
  const until = monthYear(a.until);
  return `Tax abatement · ${LAW[a.law]?.short ?? "Other"}${until ? ` · until ${until}` : ""}`;
}

export default function AbatementNote({ p }: { p: Property }) {
  const a = p.abatement;
  if (!a) return null;
  if (a.status === "ended") {
    const before = p.assessment[a.year - 1], after = p.assessment[a.year];
    return (
      <div className="alert" role="note">
        <span className="ico" aria-hidden="true">i</span>
        <b>The tax abatement on this property appears to have ended in {a.year}</b>
        <span>
          Before {a.year} only the land was taxed{before != null && <> (assessed at {money(before)})</>}; from {a.year} the
          building is taxed too{after != null && <> (assessed at {money(after)} in total)</>}. That is why the tax jumped,
          so increases across {a.year} aren&apos;t compared with other properties. Abated owners paid a separate annual
          charge before, which isn&apos;t shown here.
        </span>
      </div>
    );
  }
  const since = monthYear(a.since), until = monthYear(a.until);
  return (
    <div className="alert calm" role="note">
      <span className="ico" aria-hidden="true">i</span>
      <b>This property has {LAW[a.law]?.long ?? "a tax abatement"}{since ? `, since ${since}` : ""}</b>
      <span>
        {a.full ? "The whole property is exempt from regular tax" : "The building is exempt from regular tax; only the land is taxed"}
        {a.exempt_value != null && <> ({money(a.exempt_value)} of assessed value is exempt)</>}. Instead, the owner pays an
        annual charge set in the abatement agreement, which the tax figures here don&apos;t include.
        {until && <> The exemption runs until <b>{until}</b>; after that, regular tax applies to the full value, so expect a big step up.</>}
      </span>
    </div>
  );
}
