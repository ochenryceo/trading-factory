import { useState, useEffect, useRef, useCallback } from 'react';

const POLL_INTERVAL = 5000;

const ENDPOINTS = {
  system: '/api/system',
  discovery: '/api/discovery',
  brain: '/api/brain',
  drift: '/api/drift',
  prop: '/api/prop',
  strategies: '/api/strategies',
  control: '/api/control',
  alerts: '/api/alerts',
  lineage: '/api/lineage',
  trades: '/api/trades',
  fitnessHistory: '/api/fitness-history',
  health: '/api/health',
  intelligence: '/api/intelligence',
};

export function useApi() {
  const [data, setData] = useState({});
  const [connected, setConnected] = useState(false);
  const intervalRef = useRef(null);

  const fetchAll = useCallback(async () => {
    const results = {};
    let anySuccess = false;

    const fetches = Object.entries(ENDPOINTS).map(async ([key, url]) => {
      try {
        const res = await fetch(url);
        if (res.ok) {
          results[key] = await res.json();
          anySuccess = true;
        }
      } catch {
        // silently fail per-endpoint
      }
    });

    await Promise.all(fetches);
    
    if (anySuccess) {
      setData(prev => ({ ...prev, ...results }));
      setConnected(true);
    } else {
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    intervalRef.current = setInterval(fetchAll, POLL_INTERVAL);
    return () => clearInterval(intervalRef.current);
  }, [fetchAll]);

  return { data, connected };
}
