import { useState, useEffect, useCallback } from 'react';

export interface AuthUser {
  userId: string;
  email: string;
  name: string;
}

const STORAGE_KEY = 'patent_agent_jwt';

export function useAuth() {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlToken = params.get('token');
    const urlError = params.get('error');

    // Strip auth params from URL without reloading
    if (urlToken || urlError) {
      const clean = window.location.pathname;
      window.history.replaceState({}, '', clean);
    }

    if (urlError === 'unauthorized_domain') {
      setAuthError('Only @oregonstate.edu accounts are allowed.');
      setLoading(false);
      return;
    }

    const resolved = urlToken ?? localStorage.getItem(STORAGE_KEY);
    if (!resolved) {
      setLoading(false);
      return;
    }

    if (urlToken) {
      localStorage.setItem(STORAGE_KEY, urlToken);
    }

    // Validate token against /auth/me
    fetch('/auth/me', { headers: { Authorization: `Bearer ${resolved}` } })
      .then((res) => {
        if (!res.ok) throw new Error('invalid');
        return res.json();
      })
      .then((data: AuthUser) => {
        setToken(resolved);
        setUser(data);
      })
      .catch(() => {
        localStorage.removeItem(STORAGE_KEY);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(() => {
    window.location.href = '/auth/github';
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setToken(null);
    setUser(null);
  }, []);

  const getToken = useCallback(() => token, [token]);

  return { token, user, loading, authError, login, logout, getToken };
}
