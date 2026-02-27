// Always use relative paths so requests flow through Vite's dev proxy (→ localhost:8000)
// and Nginx in production. This works regardless of the hostname used to access the site.
export const API_BASE = '/api';

export const WS_BASE = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`;
