// Centralized API configuration.
// Set VITE_API_URL in .env.production when deploying (defaults to local dev backend).
const API_HOST = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const API_BASE = `${API_HOST}/api/v1`;
export const WS_BASE = `${API_HOST.replace(/^http/, 'ws')}/api/v1/ws`;

export const getAuthHeaders = () => {
  const token = localStorage.getItem('caredesk_token');
  return {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  };
};
