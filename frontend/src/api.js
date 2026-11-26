const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

async function requestJson(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

export function fetchDashboard({ zone = 'All', category = 'All', status = 'Flagged' } = {}) {
  const params = new URLSearchParams({ zone, category, status });
  return requestJson(`/api/dashboard?${params.toString()}`);
}

export function searchConsumers(query = '') {
  const params = new URLSearchParams({ q: query });
  return requestJson(`/api/consumers?${params.toString()}`);
}

export function fetchConsumerExplanation(consumerId) {
  return requestJson(`/api/consumer/${encodeURIComponent(consumerId)}`);
}

export function predictLiveReading({ consumer_id, units_used, save_record }) {
  return requestJson('/api/predict_reading', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ consumer_id, units_used, save_record }),
  });
}

export function addConsumer({ consumer_id, area_zone, category, baseline_kwh }) {
  return requestJson('/api/add_consumer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ consumer_id, area_zone, category, baseline_kwh }),
  });
}

export function verifyInspection({ consumer_id, outcome, remarks }) {
  return requestJson('/api/verify_inspection', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ consumer_id, outcome, remarks }),
  });
}

export function retrainModel() {
  return requestJson('/api/retrain', { method: 'POST' });
}
