import { useEffect, useState } from 'react';
import { UserPlus, X } from 'lucide-react';
import { addConsumer } from '../api.js';

export default function AddConsumerModal({
  open,
  onClose,
  zones = [],
  categories = [],
  nextConsumerId = 'KA-55345',
  onSuccess,
}) {
  const [consumerId, setConsumerId] = useState('');
  const [areaZone, setAreaZone] = useState('');
  const [category, setCategory] = useState('');
  const [baselineKwh, setBaselineKwh] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setConsumerId('');
      setAreaZone(zones[0] || '');
      setCategory(categories[0] || '');
      setBaselineKwh('');
      setError('');
    }
  }, [open, zones, categories]);

  if (!open) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      const created = await addConsumer({
        consumer_id: consumerId.trim(),
        area_zone: areaZone,
        category,
        baseline_kwh: parseFloat(baselineKwh),
      });
      onSuccess(created);
      onClose();
    } catch (err) {
      setError(err.message || 'Registration failed.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs"
      role="dialog"
      aria-modal="true"
    >
      <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl w-full max-w-md overflow-hidden">
        <div className="px-6 py-4 bg-[#0F172A] text-white flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <UserPlus className="w-5 h-5 text-emerald-400" />
            <h3 className="text-base font-bold">Register New Consumer</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-white p-1"
            aria-label="Close modal"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="p-3 rounded-lg bg-[#FEF2F2] border border-red-200 text-[#DC2626] text-xs font-medium">
              {error}
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-600 mb-1.5">
              Consumer ID <span className="text-slate-400 font-normal lowercase">(optional)</span>
            </label>
            <input
              type="text"
              value={consumerId}
              onChange={(e) => setConsumerId(e.target.value)}
              placeholder={`Auto-generated e.g. ${nextConsumerId}`}
              autoComplete="off"
              className="w-full px-3.5 py-2.5 text-sm font-mono bg-slate-50 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white"
            />
            <p className="mt-1 text-[11px] text-slate-400">
              Leave blank to auto-assign <strong className="font-mono text-slate-600">{nextConsumerId}</strong>.
            </p>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-600 mb-1.5">
              ESCOM Area Zone
            </label>
            <select
              value={areaZone}
              onChange={(e) => setAreaZone(e.target.value)}
              required
              className="w-full px-3.5 py-2.5 text-sm bg-slate-50 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white"
            >
              {zones.map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-600 mb-1.5">
              Tariff Category
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              required
              className="w-full px-3.5 py-2.5 text-sm bg-slate-50 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white"
            >
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-600 mb-1.5">
              Baseline Monthly Consumption (kWh)
            </label>
            <input
              type="number"
              min="1"
              step="0.1"
              value={baselineKwh}
              onChange={(e) => setBaselineKwh(e.target.value)}
              placeholder="e.g. 420.0"
              required
              className="w-full px-3.5 py-2.5 text-sm font-mono bg-slate-50 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white"
            />
          </div>

          <div className="pt-2 flex items-center justify-end gap-2.5">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-xs font-semibold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 rounded-lg transition-colors shadow-xs"
            >
              {submitting ? 'Registering...' : 'Register Consumer'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
