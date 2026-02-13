const isProduction = import.meta.env.PROD;

export const API_BASE = isProduction ? '/api' : 'http://localhost:8000/api';

export const WS_BASE = isProduction
  ? `ws://${window.location.host}/ws`
  : 'ws://localhost:8000/ws';
