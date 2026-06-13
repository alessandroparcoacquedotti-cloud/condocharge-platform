import { useEffect, useMemo, useState } from "react";

export type QueryState<T> = {
  data: T | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  refetch: () => void;
};

export type UseQueryOptions = {
  refetchIntervalMs?: number;
};

export function useQuery<T>(fetcher: () => Promise<T>, options: UseQueryOptions = {}): QueryState<T> {
  const [tick, setTick] = useState(0);
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refetch = useMemo(() => () => setTick((t) => t + 1), []);

  useEffect(() => {
    const interval = options.refetchIntervalMs ?? 0;
    if (!interval) return;
    const id = window.setInterval(() => setTick((t) => t + 1), interval);
    return () => window.clearInterval(id);
  }, [options.refetchIntervalMs]);

  useEffect(() => {
    let alive = true;
    setError(null);
    if (data == null) {
      setLoading(true);
      setRefreshing(false);
    } else {
      setLoading(false);
      setRefreshing(true);
    }
    fetcher()
      .then((result) => {
        if (!alive) return;
        setData(result);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        if (typeof e === "object" && e && "message" in e && typeof (e as any).message === "string") {
          setError((e as any).message);
        } else {
          setError(String(e));
        }
      })
      .finally(() => {
        if (!alive) return;
        setLoading(false);
        setRefreshing(false);
      });
    return () => {
      alive = false;
    };
  }, [fetcher, tick]);

  return { data, loading, refreshing, error, refetch };
}
