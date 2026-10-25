import Link from "next/link";
import MapView from "@/components/MapView";
import Search from "@/components/Search";
import { getMeta } from "@/lib/data";

export const revalidate = 3600;

export default async function Home() {
  const meta = await getMeta();
  const base = meta?.base_year ?? 2019, last = meta?.last_year ?? 2026;
  return (
    <>
      <section className="hero">
        <h1>How has your property tax changed?</h1>
        <p className="lede">
          Look up any Jersey City property to see its tax since {base}, how that compares with similar homes nearby,
          and a rough check of whether appealing your {meta?.ratio_year ?? 2027} assessment could help.
        </p>
        <Search autoFocus />
      </section>
      <section aria-label="Map">
        <MapView baseYear={base} lastYear={last} />
        <p className="small muted" style={{ marginTop: 8 }}>
          Each dot is a property. Drag to move, scroll or use + and − to zoom, and select a dot to open it.{" "}
          <Link href="/appeal">How tax appeals work →</Link>
        </p>
      </section>
    </>
  );
}
