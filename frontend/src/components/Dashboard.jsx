import { useEffect, useState } from 'react';
import ShapChart from './ShapChart.jsx';

function badgeStyle(status) {
  if (status === 'Inspect') return 'bg-red-50 text-red-700 border border-red-200';
  if (status === 'Watchlist') return 'bg-amber-50 text-amber-700 border border-amber-200';
  return 'bg-emerald-50 text-emerald-700 border border-emerald-200';
}

export default function Dashboard({
  dashboard,
  filters,
  onFilterChange,
  onResetFilters,
  selectedConsumer,
  consumerError,
  onSelectConsumer,
  onVerifyInspection,
  loading,
}) {
  const [remarks, setRemarks] = useState('');
  const [verifyNote, setVerifyNote] = useState('');

  useEffect(() => {
    setRemarks('');
    setVerifyNote('');
  }, [selectedConsumer?.consumer_id]);

  const kpis = dashboard?.kpis || {};
  const rows = dashboard?.rows || [];
  const zones = dashboard?.zones || [];
  const categories = dashboard?.categories || [];

  const f = selectedConsumer?.features || {};
  const p = selectedConsumer?.peer_stats || {};
  const pct = (f.pct_change_from_avg || 0) * 100;

  async function handleVerify(outcome) {
    if (!selectedConsumer) return;
    setVerifyNote('');
    try {
      const res = await onVerifyInspection({
        consumer_id: selectedConsumer.consumer_id,
        outcome,
        remarks,
      });
      setVerifyNote(`Saved "${res.outcome}" for ${res.consumer_id}.`);
    } catch (err) {
      setVerifyNote(err.message);
    }
  }

  return (
    <div className="space-y-5">
      {/* 4 Simple KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-xs font-semibold text-slate-500 uppercase">Monitored</div>
          <div className="mt-1 text-2xl font-bold font-mono text-slate-900">
            {(kpis.consumers_monitored ?? 0).toLocaleString()}
          </div>
          <div className="text-xs text-slate-400 mt-1">{filters.zone}</div>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-xs font-semibold text-slate-500 uppercase">Flagged (&ge; 40)</div>
          <div className="mt-1 text-2xl font-bold font-mono text-amber-600">
            {(kpis.cases_flagged ?? 0).toLocaleString()}
          </div>
          <div className="text-xs text-slate-400 mt-1">
            {Number(kpis.flagged_pct ?? 0).toFixed(2)}% of monitored
          </div>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-xs font-semibold text-slate-500 uppercase">High Risk (&ge; 70)</div>
          <div className="mt-1 text-2xl font-bold font-mono text-red-600">
            {(kpis.high_risk ?? 0).toLocaleString()}
          </div>
          <div className="text-xs text-slate-400 mt-1">
            {Number(kpis.high_risk_pct ?? 0).toFixed(2)}% priority inspect
          </div>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="text-xs font-semibold text-slate-500 uppercase">Verified Theft</div>
          <div className="mt-1 text-2xl font-bold font-mono text-emerald-600">
            {(kpis.verified_detections ?? 0).toLocaleString()}
          </div>
          <div className="text-xs text-slate-400 mt-1">
            {(kpis.total_inspections ?? 0).toLocaleString()} field checks logged
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white rounded-xl border border-slate-200 p-4 flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[180px]">
          <label className="block text-xs font-semibold text-slate-500 mb-1">ESCOM Zone</label>
          <select
            value={filters.zone}
            onChange={(e) => onFilterChange({ ...filters, zone: e.target.value })}
            className="w-full px-3 py-2 text-sm bg-slate-50 border border-slate-200 rounded-lg"
          >
            <option value="All">All Zones</option>
            {zones.map((z) => (
              <option key={z} value={z}>{z}</option>
            ))}
          </select>
        </div>

        <div className="flex-1 min-w-[160px]">
          <label className="block text-xs font-semibold text-slate-500 mb-1">Tariff Category</label>
          <select
            value={filters.category}
            onChange={(e) => onFilterChange({ ...filters, category: e.target.value })}
            className="w-full px-3 py-2 text-sm bg-slate-50 border border-slate-200 rounded-lg"
          >
            <option value="All">All Categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>

        <div className="flex-1 min-w-[160px]">
          <label className="block text-xs font-semibold text-slate-500 mb-1">Risk Status</label>
          <select
            value={filters.status}
            onChange={(e) => onFilterChange({ ...filters, status: e.target.value })}
            className="w-full px-3 py-2 text-sm bg-slate-50 border border-slate-200 rounded-lg"
          >
            <option value="Flagged">Flagged (&ge; 40)</option>
            <option value="Inspect">Inspect (&ge; 70)</option>
            <option value="Watchlist">Watchlist (40–69)</option>
            <option value="Normal">Normal (&lt; 40)</option>
            <option value="All">All Statuses</option>
          </select>
        </div>

        <button
          type="button"
          onClick={onResetFilters}
          className="px-4 py-2 text-sm font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg"
        >
          Reset
        </button>
      </div>

      {/* Table + Case Inspector */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
        {/* Ranked Table */}
        <div className="lg:col-span-7 bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900">Ranked Inspection Queue</h2>
            <span className="text-xs text-slate-500">
              {loading ? 'Loading...' : `${rows.length.toLocaleString()} shown of ${(dashboard?.total_matching ?? 0).toLocaleString()}`}
            </span>
          </div>

          <div className="table-scroll max-h-[600px] overflow-auto">
            <table className="w-full text-left border-collapse text-sm">
              <thead className="sticky top-0 bg-slate-50 border-b border-slate-200 text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2.5 px-3">Consumer ID</th>
                  <th className="py-2.5 px-3">Zone</th>
                  <th className="py-2.5 px-3">Score</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3 text-right">Latest / Avg</th>
                  <th className="py-2.5 px-3 text-right">% Diff</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.length > 0 ? (
                  rows.map((r) => {
                    const active = selectedConsumer?.consumer_id === r.consumer_id;
                    const diff = Number(r.pct_change_from_avg || 0) * 100;
                    return (
                      <tr
                        key={r.consumer_id}
                        onClick={() => onSelectConsumer(r.consumer_id)}
                        className={`cursor-pointer ${active ? 'bg-blue-50' : 'hover:bg-slate-50'}`}
                      >
                        <td className="py-2.5 px-3 font-mono font-semibold text-slate-900">{r.consumer_id}</td>
                        <td className="py-2.5 px-3 text-xs text-slate-600">
                          <div>{r.area_zone}</div>
                          <div className="text-slate-400">{r.category}</div>
                        </td>
                        <td className="py-2.5 px-3 font-mono font-bold">{r.risk_score}</td>
                        <td className="py-2.5 px-3">
                          <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${badgeStyle(r.status)}`}>
                            {r.status}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono text-xs">
                          {Number(r.latest_kwh).toFixed(1)} / {Number(r.avg_6m).toFixed(1)}
                        </td>
                        <td className={`py-2.5 px-3 text-right font-mono text-xs font-semibold ${diff < -25 ? 'text-red-600' : 'text-slate-600'}`}>
                          {diff >= 0 ? '+' : ''}{diff.toFixed(1)}%
                        </td>
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-slate-400">No matching consumers.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Case Explanation Inspector */}
        <div className="lg:col-span-5 bg-white rounded-xl border border-slate-200 p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <div>
              <h2 className="text-sm font-bold text-slate-900">Case Explanation (SHAP)</h2>
              <p className="text-xs text-slate-500">Click any row to inspect</p>
            </div>
            {selectedConsumer && (
              <span className={`px-2.5 py-1 rounded-full text-xs font-bold ${badgeStyle(selectedConsumer.status)}`}>
                Score: {selectedConsumer.risk_score}/100 ({selectedConsumer.status})
              </span>
            )}
          </div>

          {consumerError && (
            <div className="p-3 rounded-lg bg-red-50 text-red-700 text-xs">{consumerError}</div>
          )}

          {!selectedConsumer && !consumerError && (
            <div className="py-12 text-center text-sm text-slate-400">Select a consumer to inspect.</div>
          )}

          {selectedConsumer && !consumerError && (
            <>
              <div>
                <div className="text-lg font-bold font-mono text-slate-900">{selectedConsumer.consumer_id}</div>
                <div className="text-xs text-slate-500">
                  {selectedConsumer.area_zone} · {selectedConsumer.category}
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200">
                  <div className="text-[11px] text-slate-500">Latest</div>
                  <div className="font-mono text-sm font-bold">{Number(f.latest_kwh || 0).toFixed(1)} kWh</div>
                </div>
                <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200">
                  <div className="text-[11px] text-slate-500">6M Avg</div>
                  <div className="font-mono text-sm font-bold">{Number(f.avg_6m || 0).toFixed(1)} kWh</div>
                </div>
                <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200">
                  <div className="text-[11px] text-slate-500">Peer Ratio</div>
                  <div className="font-mono text-sm font-bold">{Number(f.peer_ratio || 0).toFixed(2)}x</div>
                </div>
              </div>

              <div className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-700 leading-relaxed">
                Consumption changed by <strong className="font-mono">{pct >= 0 ? '+' : ''}{pct.toFixed(1)}%</strong> vs. 6M baseline
                (peer median <span className="font-mono">{Number(p.peer_median_kwh || 0).toFixed(1)} kWh</span>,
                load utilization <span className="font-mono">{(Number(f.load_utilization || 0) * 100).toFixed(1)}%</span>).
              </div>

              <ShapChart contributions={selectedConsumer.shap_contributions || []} height={270} />

              {/* Field Verification */}
              <div className="pt-3 border-t border-slate-200 space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-semibold text-slate-700">Field Verification</span>
                  <span className="text-slate-500">
                    {selectedConsumer.latest_inspection?.outcome || `Label: ${selectedConsumer.ground_truth === 1 ? 'Theft' : 'Normal'}`}
                  </span>
                </div>
                <input
                  type="text"
                  value={remarks}
                  onChange={(e) => setRemarks(e.target.value)}
                  placeholder="Optional inspection notes..."
                  className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg"
                />
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => handleVerify('Confirmed Theft')}
                    className="py-2 rounded-lg text-xs font-semibold bg-red-600 hover:bg-red-700 text-white"
                  >
                    Confirm Theft
                  </button>
                  <button
                    type="button"
                    onClick={() => handleVerify('False Alarm')}
                    className="py-2 rounded-lg text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-800"
                  >
                    Mark False Alarm
                  </button>
                </div>
                {verifyNote && <div className="text-xs text-emerald-700 font-medium">{verifyNote}</div>}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
