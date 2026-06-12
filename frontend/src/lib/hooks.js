import { useState, useEffect, useCallback, useRef } from 'react';

export function useLocalStorage(key, initial) {
  const [value, setValue] = useState(() => {
    try {
      const stored = localStorage.getItem(key);
      return stored ? JSON.parse(stored) : initial;
    } catch { return initial; }
  });
  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(value));
  }, [key, value]);
  return [value, setValue];
}

export function useFetch(url, refreshIntervalMs = 0) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastFetched, setLastFetched] = useState(null);
  const urlRef = useRef(url);
  urlRef.current = url;
  const fetchData = useCallback(async () => {
    const currentUrl = urlRef.current;
    if (!currentUrl) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(currentUrl);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
      setLastFetched(new Date());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { fetchData(); }, [url, fetchData]);
  useEffect(() => {
    if (!refreshIntervalMs) return;
    const id = setInterval(fetchData, refreshIntervalMs);
    return () => clearInterval(id);
  }, [fetchData, refreshIntervalMs]);
  return { data, loading, error, refetch: fetchData, lastFetched };
}
