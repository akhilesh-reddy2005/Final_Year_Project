import { useEffect, useRef } from 'react';
import Plotly from 'plotly.js-dist-min';

export default function ShapChart({
  contributions = [],
  title = 'SHAP Feature Attributions (+ Theft Risk | - Normal)',
  height = 290,
}) {
  const containerRef = useRef(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !contributions.length) return;

    const sorted = [...contributions].sort(
      (a, b) => Math.abs(a.risk_contribution) - Math.abs(b.risk_contribution)
    );

    const yLabels = sorted.map((item) => `${item.label} (${item.formatted_value})`);
    const xValues = sorted.map((item) => item.risk_contribution);
    const colors = xValues.map((v) => (v >= 0 ? '#DC2626' : '#059669'));
    const maxAbs = Math.max(...xValues.map((v) => Math.abs(v)), 0.05);

    const trace = {
      type: 'bar',
      orientation: 'h',
      y: yLabels,
      x: xValues,
      marker: { color: colors },
      text: xValues.map((v) => `${v >= 0 ? '+' : ''}${v.toFixed(3)}`),
      textposition: 'outside',
      textfont: { family: 'JetBrains Mono, monospace', size: 11 },
      hovertemplate: '<b>%{y}</b><br>SHAP Theft Impact: %{x:+.4f}<extra></extra>',
    };

    const layout = {
      title: {
        text: title,
        font: { family: 'Inter, sans-serif', size: 12, color: '#334155' },
      },
      font: { family: 'Inter, sans-serif', size: 11, color: '#475569' },
      xaxis: {
        title: { text: 'SHAP Contribution', font: { size: 11 } },
        range: [-maxAbs * 1.38, maxAbs * 1.38],
        zeroline: true,
        zerolinecolor: '#94A3B8',
        zerolinewidth: 1.5,
        gridcolor: '#F1F5F9',
      },
      yaxis: { automargin: true },
      margin: { l: 8, r: 28, t: 36, b: 36 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
    };

    Plotly.newPlot(el, [trace], layout, { responsive: true, displayModeBar: false });

    const onResize = () => Plotly.Plots.resize(el);
    window.addEventListener('resize', onResize);

    return () => {
      window.removeEventListener('resize', onResize);
      Plotly.purge(el);
    };
  }, [contributions, title]);

  return <div ref={containerRef} style={{ width: '100%', height }} />;
}
