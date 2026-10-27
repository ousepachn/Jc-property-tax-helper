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
}

export interface SearchHit {
  pin: string; // "" for a building with several units (see units)
  address: string;
  unit: string | null;
  kind: string | null;
  units?: number; // a building: how many properties share this address
}

// map points: [pin, lat, lon, Q4 bill change vs a year earlier, change over 5 years]
export type MapPoint = [string, number, number, number | null, number | null];
