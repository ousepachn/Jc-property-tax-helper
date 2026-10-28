// Shapes written by pipeline/build_site.py. Public fields only.

export type Score = "likely" | "possible" | "unlikely" | "not_enough_data" | "not_applicable";

export interface Neighbor {
  pin: string;
  address: string;
  unit: string | null;
  sq_ft: number | null;
  year_built: number | null;
  miles: number;
  lat: number;
  lon: number;
  change: number | null;
}

export interface Sale {
  pin: string;
  lat: number;
  lon: number;
  address: string;
  unit: string | null;
  sq_ft: number;
  year_built: number | null;
  sale_date: string;
  price: number;
  ppsf: number;
  miles: number;
}

export interface Appeal {
  score: Score;
  reason?: string;
  notes?: string[];
  estimated_value?: number;
  ratio?: number;
  median_ppsf?: number;
  ppsf_spread?: number;
  sales?: number;
  size_band?: number | null;
  radius_mi?: number | null;
  ratio_range?: { avg: number; lo: number; hi: number };
  fair_range?: [number, number];
  comparable_sales?: Sale[];
}

export interface Property {
  pin: string;
  town: string;
  address: string;
  unit: string | null;
  kind: string | null;
  class: string;
  sq_ft: number | null;
  year_built: number | null;
  building: string | null;
  lat: number | null;
  lon: number | null;
  abated: boolean;
  assessment: Record<string, number | null>;
  tax: Record<string, number | null>;
  tax_source: "bills" | "estimated";
  base_year: number;
  added_assessment_years: number[];
  appeal_credits: Record<string, number | null>;
  change: number | null;
  change_q4?: number | null; // fourth-quarter bill of the last year vs a year earlier
  change_5y?: number | null;
  q4_bill?: Record<string, number | null>;
  permits?: Permits;
  abatement?: Abatement | null;
  abatement_charges?: Record<string, number | null>; // included in tax: what an abated property paid instead
  building_compare?: BuildingCompare | null;
  compare: {
    count: number;
    size_band?: number | null;
    radius_mi?: number | null;
    reason?: string | null;
    median_change?: number | null;
    median_tax_by_year?: Record<string, number | null>;
    city_percentile?: number | null;
    city_group_size?: number;
    list?: Neighbor[];
  };
  appeals_nearby?: { since: number; compared: number; won: number; median_reduction: number | null };
  appeal: Appeal;
}

export type AbatementLaw = "long_term" | "five_year" | "affordable" | "urban_renewal" | "other";

export type Abatement =
  | { status: "active"; law: AbatementLaw; statute: string | null; since: string | null; until: string | null;
      full: boolean; exempt_value: number | null }
  | { status: "ended"; year: number };

export interface BuildingUnit { pin: string; unit: string; floor: number | null; sq_ft: number; value: number; ppsf: number }

// this condo unit against the other units in its building: full assessment (taxable + abated) per sq ft
export interface BuildingCompare {
  units: number;
  compared: number;
  abated_units: number;
  median_ppsf: number;
  ppsf: number;
  value: number;
  floor: number | null;
  vs_median: number;
  vs_floor: number | null; // vs the building's trend by floor, when it has enough floors
  above: boolean;
  higher_than: number; // % of compared units assessed lower per sq ft
  list: BuildingUnit[];
}

export interface CityStats {
  taxable_value: number;
  levy_estimate: number;
  rate: number;
  records: number;
  exempt_value: number;
  by_class: { label: string; value: number; share: number | null }[];
  abatement: {
    properties: number; units: number; buildings: number; full: number; value: number;
    share_of_value: number | null; regular_tax_equivalent: number; by_law: Record<string, number>;
    ending_by: number; ending_soon: number; ended_recently: number; ended_since: number;
  };
}

export type PermitRelevance = "likely" | "possible" | "unlikely" | "lower";

export interface Permit {
  no: string;
  type: string;
  category: string;
  status: string;
  issued: string | null;
  applied?: string | null;
  finished: string | null;
  description: string | null;
  relevance: PermitRelevance;
  done: boolean;
  building: boolean; // the building's permit, not this unit's
}

export interface Permits {
  count: number;
  building_count: number;
  list: Permit[];
  outlook: { state: "in_progress" | "may_be_added" | "reflected"; permit: string; relevance: PermitRelevance; year: number } | null;
  renovated: boolean;
}

export interface Meta {
  town: string;
  county_district: string;
  built_at: string;
  tax_source: "bills" | "estimated";
  base_year: number;
  last_year: number;
  ratio_year: number;
  ratio: { avg: number; lo: number; hi: number };
  valuation_date: string;
  properties: number;
  data_as_of: string | null;
  permits?: boolean;
  trend_years?: number;
  rate?: Record<string, number>; // general tax rate per $100 of assessed value
  median_change_q4?: number | null;
  median_change_5y?: number | null;
  city?: CityStats;
}

export interface SearchHit {
  pin: string; // "" for a building with several units (see units)
  address: string;
  unit: string | null;
  kind: string | null;
  units?: number; // a building: how many properties share this address
}

// map points: [pin, lat, lon, Q4 bill change vs a year earlier, change over 5 years,
//              abatement: 0 none, 1 long-term, 2 five-year, 3 other, 4 ended recently]
export type MapPoint = [string, number, number, number | null, number | null, number];
