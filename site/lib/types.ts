// Shapes written by pipeline/build_site.py. Public fields only.

export type Score = "likely" | "possible" | "unlikely" | "not_enough_data" | "not_applicable";

export interface Neighbor {
  pin: string;
  address: string;
  unit: string | null;
  sq_ft: number | null;
  year_built: number | null;
  miles: number;
  change: number | null;
}

export interface Sale {
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
}

export interface SearchHit {
  pin: string;
  address: string;
  unit: string | null;
  kind: string | null;
}

// map points: [pin, lat, lon, change, appeal score]
export type MapPoint = [string, number, number, number | null, Score | null];
