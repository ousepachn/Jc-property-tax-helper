import CityStats from "@/components/CityStats";
import HomeMap from "@/components/HomeMap";
import Search from "@/components/Search";
import { getMeta } from "@/lib/data";

export const revalidate = 3600;

export default async function Home() {
  const meta = await getMeta();
  const last = meta?.last_year ?? 2026;
  return (
    <>
      <section className="home">
        <h1 className="display">
          What&apos;s happening to your <em>property tax?</em>
        </h1>
        <Search autoFocus large />
        <p className="hint">Any Jersey City address. For a condo, add the unit: “77 Hudson St 1205”.</p>
      </section>
      <HomeMap
        lastYear={last}
        baseYear={meta?.base_year ?? 2019}
        trendYears={meta?.trend_years ?? null}
        medianQ4={meta?.median_change_q4 ?? null}
        median5y={meta?.median_change_5y ?? null}
        abatedCount={meta?.city?.abatement.properties ?? null}
      />
      {meta?.city && (
        <CityStats c={meta.city} year={last}
          asOf={meta.data_as_of ? new Date(meta.data_as_of + "T12:00:00").toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" }) : null} />
      )}
    </>
  );
}
