import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchConsumerExplanation,
  fetchDashboard,
  retrainModel,
  searchConsumers,
  verifyInspection,
} from './api.js';
import AddConsumerModal from './components/AddConsumerModal.jsx';
import BillCollector from './components/BillCollector.jsx';
import Dashboard from './components/Dashboard.jsx';

const DEFAULT_FILTERS = { zone: 'All', category: 'All', status: 'Flagged' };

export default function App() {
  const [tab, setTab] = useState('dashboard');
  const [addOpen, setAddOpen] = useState(false);

  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);

  const [selectedConsumer, setSelectedConsumer] = useState(null);
  const [consumerError, setConsumerError] = useState('');

  const [autocompleteIds, setAutocompleteIds] = useState([]);
  const [searchId, setSearchId] = useState('');
  const [retraining, setRetraining] = useState(false);
  const [toast, setToast] = useState(null);

  const searchTimer = useRef(null);
  const toastTimer = useRef(null);

  const showToast = useCallback((message, isError = false) => {
    setToast({ message, isError });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 5000);
  }, []);

  const loadConsumer = useCallback(async (consumerId) => {
    if (!consumerId) return;
    setConsumerError('');
    try {
      const data = await fetchConsumerExplanation(consumerId);
      setSelectedConsumer(data);
    } catch (err) {
      setConsumerError(err.message || 'Consumer not found.');
    }
  }, []);

  const loadDashboard = useCallback(
    async (activeFilters, preferId = null) => {
      setLoading(true);
      try {
        const data = await fetchDashboard(activeFilters);
        setDashboard(data);
        setAutocompleteIds(data.seed_consumer_ids || []);
        const targetId = preferId || data.rows?.[0]?.consumer_id;
        if (targetId) {
          loadConsumer(targetId);
        } else {
          setSelectedConsumer(null);
        }
      } catch (err) {
        showToast(err.message || 'Failed to load data from backend.', true);
      } finally {
        setLoading(false);
      }
    },
    [loadConsumer, showToast]
  );

  useEffect(() => {
    loadDashboard(filters);
  }, [filters, loadDashboard]);

  const handleAutocomplete = useCallback((q) => {
    clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(async () => {
      try {
        const res = await searchConsumers(q);
        setAutocompleteIds(res.consumer_ids || []);
      } catch (_) {}
    }, 150);
  }, []);

  async function handleVerifyInspection({ consumer_id, outcome, remarks }) {
    const res = await verifyInspection({ consumer_id, outcome, remarks });
    setSelectedConsumer((prev) =>
      prev && prev.consumer_id === res.consumer_id
        ? { ...prev, ground_truth: res.ground_truth, latest_inspection: res.inspection }
        : prev
    );
    const refreshed = await fetchDashboard(filters);
    setDashboard(refreshed);
    showToast(`Marked ${res.consumer_id} as ${res.outcome}.`);
    return res;
  }

  async function handleRetrain() {
    setRetraining(true);
    try {
      const summary = await retrainModel();
      await loadDashboard(filters, selectedConsumer?.consumer_id);
      showToast(`Retrained model — F1: ${summary.metrics.f1_score}, AUC: ${summary.metrics.roc_auc}`);
    } catch (err) {
      showToast(err.message || 'Retraining failed.', true);
    } finally {
      setRetraining(false);
    }
  }

  function handleQuickSearch(e) {
    e.preventDefault();
    const cid = searchId.trim().toUpperCase();
    if (!cid) return;
    setTab('dashboard');
    loadConsumer(cid);
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900">
      {/* Simple Top Header */}
      <header className="bg-[#0F172A] text-white border-b border-slate-800">
        <div className="max-w-7xl mx-auto px-4 py-3.5 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-bold tracking-tight">BESCOM GridGuard AI</h1>
            <p className="text-xs text-slate-400">Karnataka ESCOM Electricity Theft Detection</p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <form onSubmit={handleQuickSearch} className="flex gap-1.5">
              <input
                type="text"
                value={searchId}
                onChange={(e) => {
                  setSearchId(e.target.value);
                  handleAutocomplete(e.target.value);
                }}
                list="consumerIdList"
                placeholder="Search ID (KA-10000)"
                className="px-3 py-1.5 text-xs font-mono text-slate-900 bg-white rounded-lg w-40"
              />
              <button
                type="submit"
                className="px-3 py-1.5 text-xs font-semibold bg-slate-700 hover:bg-slate-600 rounded-lg"
              >
                Inspect
              </button>
            </form>

            <button
              type="button"
              onClick={() => setAddOpen(true)}
              className="px-3 py-1.5 text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 rounded-lg"
            >
              + Add Consumer
            </button>

            <button
              type="button"
              disabled={retraining}
              onClick={handleRetrain}
              className="px-3 py-1.5 text-xs font-semibold bg-amber-500 hover:bg-amber-400 text-slate-950 disabled:opacity-60 rounded-lg"
            >
              {retraining ? 'Retraining...' : 'Retrain Model'}
            </button>
          </div>
        </div>
      </header>

      <datalist id="consumerIdList">
        {autocompleteIds.map((cid) => (
          <option key={cid} value={cid} />
        ))}
      </datalist>

      {/* Main Container */}
      <main className="max-w-7xl mx-auto px-4 py-5 space-y-5">
        {/* Simple 2-Tab Navigation */}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setTab('dashboard')}
            className={`px-4 py-2 text-sm font-semibold rounded-lg border ${
              tab === 'dashboard'
                ? 'bg-blue-600 text-white border-blue-600'
                : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
            }`}
          >
            Theft Risk Dashboard
          </button>
          <button
            type="button"
            onClick={() => setTab('collector')}
            className={`px-4 py-2 text-sm font-semibold rounded-lg border ${
              tab === 'collector'
                ? 'bg-blue-600 text-white border-blue-600'
                : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
            }`}
          >
            Bill Collector Entry
          </button>
        </div>

        {tab === 'dashboard' ? (
          <Dashboard
            dashboard={dashboard}
            filters={filters}
            onFilterChange={setFilters}
            onResetFilters={() => setFilters(DEFAULT_FILTERS)}
            selectedConsumer={selectedConsumer}
            consumerError={consumerError}
            onSelectConsumer={loadConsumer}
            onVerifyInspection={handleVerifyInspection}
            loading={loading}
          />
        ) : (
          <BillCollector
            onSearchInput={handleAutocomplete}
            onSyncedReading={(reading) => loadDashboard(filters, reading.consumer_id)}
          />
        )}
      </main>

      <AddConsumerModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        zones={dashboard?.zones || []}
        categories={dashboard?.categories || []}
        nextConsumerId={dashboard?.next_consumer_id || 'KA-55345'}
        onSuccess={async (created) => {
          await loadDashboard(filters, created.consumer_id);
          showToast(`Registered ${created.consumer_id} (Score: ${created.risk_score}/100).`);
        }}
      />

      {toast && (
        <div
          className={`fixed bottom-4 right-4 px-4 py-2.5 rounded-lg shadow-lg text-xs font-semibold ${
            toast.isError ? 'bg-red-600 text-white' : 'bg-slate-900 text-white'
          }`}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}
