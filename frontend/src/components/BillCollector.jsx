import { useState } from 'react';
import { predictLiveReading } from '../api.js';
import ShapChart from './ShapChart.jsx';

function verdictStyle(status) {
  if (status === 'Inspect') {
    return {
      box: 'bg-red-50 border-red-200 text-red-900',
      label: 'HIGH RISK — Alert BESCOM Vigilance Squad',
    };
  }
  if (status === 'Watchlist') {
    return {
      box: 'bg-amber-50 border-amber-200 text-amber-900',
      label: 'Watchlist — Monitor Next Billing Cycle',
    };
  }
  return {
    box: 'bg-emerald-50 border-emerald-200 text-emerald-900',
    label: 'Normal — Generate Standard Bill',
  };
}

export default function BillCollector({ onSearchInput, onSyncedReading }) {
  const [consumerId, setConsumerId] = useState('');
  const [unitsUsed, setUnitsUsed] = useState('');
  const [saveRecord, setSaveRecord] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const data = await predictLiveReading({
        consumer_id: consumerId.trim().toUpperCase(),
        units_used: parseFloat(unitsUsed),
        save_record: saveRecord,
      });
      setResult(data);
      if (data.saved && onSyncedReading) {
        onSyncedReading(data);
      }
    } catch (err) {
      setError(err.message || 'Unable to score meter reading.');
    } finally {
      setLoading(false);
    }
  }

  const verdict = result ? verdictStyle(result.status) : null;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
      {/* Entry Form */}
      <div className="lg:col-span-5 bg-white rounded-xl border border-slate-200 p-5">
        <h2 className="text-base font-bold text-slate-900">Bill Collector — Live Meter Entry</h2>
        <p className="text-xs text-slate-500 mt-0.5 mb-4">
          Enter a consumer ID and current kWh reading for instant theft risk scoring.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">Customer ID</label>
            <input
              type="text"
              value={consumerId}
              onChange={(e) => {
                setConsumerId(e.target.value);
                onSearchInput(e.target.value);
              }}
              list="consumerIdList"
              placeholder="e.g. KA-10000"
              autoComplete="off"
              required
              className="w-full px-3.5 py-2.5 text-sm font-mono bg-slate-50 border border-slate-300 rounded-lg"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">
              Current Units Used (kWh)
            </label>
            <input
              type="number"
              min="0"
              step="0.1"
              value={unitsUsed}
              onChange={(e) => setUnitsUsed(e.target.value)}
              placeholder="e.g. 140.5"
              required
              className="w-full px-3.5 py-2.5 text-lg font-mono font-bold bg-slate-50 border border-slate-300 rounded-lg"
            />
          </div>

          <label className="flex items-center gap-2 text-xs text-slate-700 cursor-pointer">
            <input
              type="checkbox"
              checked={saveRecord}
              onChange={(e) => setSaveRecord(e.target.checked)}
              className="rounded border-slate-300"
            />
            <span>Update consumer record in MongoDB</span>
          </label>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 px-4 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white text-sm font-semibold"
          >
            {loading ? 'Calculating...' : 'Calculate Risk Score'}
          </button>

          {error && <div className="p-3 rounded-lg bg-red-50 text-red-700 text-xs">{error}</div>}
        </form>
      </div>

      {/* Verdict Panel */}
      <div className="lg:col-span-7 bg-white rounded-xl border border-slate-200 p-5">
        {!result ? (
          <div className="py-16 text-center text-sm text-slate-400">
            Submit a meter reading on the left to view the live risk score and SHAP breakdown.
          </div>
        ) : (
          <div className="space-y-4">
            <div className={`p-4 rounded-xl border flex flex-wrap items-center justify-between gap-3 ${verdict.box}`}>
              <div>
                <div className="text-xs font-bold uppercase">{verdict.label}</div>
                <div className="text-lg font-bold font-mono mt-1">{result.consumer_id}</div>
                <div className="text-xs opacity-80">{result.area_zone} · {result.category}</div>
              </div>
              <div className="text-right">
                <div className="text-3xl font-extrabold font-mono">{result.risk_score}</div>
                <div className="text-[11px] font-semibold uppercase">Risk / 100</div>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-center">
              <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200">
                <div className="text-[11px] text-slate-500">6M Avg</div>
                <div className="font-mono text-sm font-bold">{result.avg_6m.toFixed(1)} kWh</div>
              </div>
              <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200">
                <div className="text-[11px] text-slate-500">Entered</div>
                <div className="font-mono text-sm font-bold">{result.units_used.toFixed(1)} kWh</div>
              </div>
              <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200">
                <div className="text-[11px] text-slate-500">% Change</div>
                <div className="font-mono text-sm font-bold">
                  {result.pct_change >= 0 ? '+' : ''}{result.pct_change.toFixed(1)}%
                </div>
              </div>
              <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200">
                <div className="text-[11px] text-slate-500">Peer Ratio</div>
                <div className="font-mono text-sm font-bold">{result.peer_ratio.toFixed(2)}x</div>
              </div>
            </div>

            <ShapChart
              contributions={result.shap_contributions || []}
              title="Live SHAP Feature Contributions"
              height={270}
            />
          </div>
        )}
      </div>
    </div>
  );
}
