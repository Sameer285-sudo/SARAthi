/**
 * useTxFilters — shared hook for hierarchical filter state.
 * Provides cascading District → AFSO → FPS → Month → Commodity filters.
 */
import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchTransactionFilters, type TxFilters } from "../api";

export function useTxFilters() {
  const [filters, setFilters] = useState<TxFilters>({});

  const { data: filterData, isLoading: filtersLoading } = useQuery({
    queryKey: ["tx-filters"],
    queryFn: fetchTransactionFilters,
    staleTime: 10 * 60 * 1000,
  });

  const fd = filterData?.filters;

  // Cascading option lists
  const districts   = fd?.districts   ?? [];
  const months      = fd?.months      ?? [];
  const commodities = fd?.commodities ?? [];

  const afsos = useMemo(() => {
    if (!fd) return [];
    if (!filters.district) return fd.afsos;
    return fd.afsos_by_district[filters.district] ?? [];
  }, [fd, filters.district]);

  const fpsList = useMemo(() => {
    if (!fd) return [];
    if (!filters.afso) return fd.fps_ids;
    return fd.fps_by_afso[filters.afso] ?? [];
  }, [fd, filters.afso]);

  const setFilter = (key: keyof TxFilters, val: string) => {
    setFilters(prev => {
      const next = { ...prev, [key]: val || undefined };
      if (key === "district") { delete next.afso; delete next.fps_id; }
      if (key === "afso")     { delete next.fps_id; }
      return next;
    });
  };

  const resetFilters = () => setFilters({});

  /** Convert filters to URLSearchParams string (for queryKey use) */
  const filterParams = useMemo(() => {
    const p = new URLSearchParams();
    if (filters.year)      p.set("year",      String(filters.year));
    if (filters.month)     p.set("month",     filters.month);
    if (filters.district)  p.set("district",  filters.district);
    if (filters.afso)      p.set("afso",      filters.afso);
    if (filters.fps_id)    p.set("fps_id",    filters.fps_id);
    if (filters.commodity) p.set("commodity", filters.commodity);
    return p.toString();
  }, [filters]);

  return {
    filters,
    setFilter,
    resetFilters,
    filterParams,
    filterOptions: {
      districts,
      afsos,
      fpsList,
      months,
      commodities,
    },
    filtersLoading,
  };
}
