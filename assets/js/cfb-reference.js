/* Reference selection uses precomputed results, never a browser model fit. */
((root, factory) => {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.CFBReference = api;
})(typeof window === 'object' ? window : globalThis, () => {
  const ranks = [2, 4, 12, 24], defaultRank = 12;
  const methodology = 'margin-of-merit-2026-11-21-no-p4-reference-12';
  const label = rank => ({2: '2nd', 4: '4th', 12: '12th', 24: '24th'})[rank];
  function choice(value) { const rank = Number(value); return ranks.includes(rank) ? rank : defaultRank; }
  function descriptor(row, rank) {
    const saved = row.references?.[rank];
    if (!ranks.includes(rank) || !saved || saved.reference_rank !== rank) throw new Error('Reference results unavailable');
    return saved;
  }
  function valid(value, row, rank) {
    return value.methodology === methodology && value.publication_ready &&
      value.schema === 'margin-of-merit-snapshot-v1' && Array.isArray(value.teams) &&
      value.season === row.season && value.week === row.week && value.reference_rank === rank;
  }
  function historyWeeks(series, snapshots, rank) {
    const published = new Set(snapshots.map(r => r.id));
    return series.weeks.filter(w => published.has(w.id) && w.references?.[rank]?.reference_rank === rank)
      .map(w => ({...w, ...w.references[rank]}));
  }
  return {ranks, defaultRank, methodology, label, choice, descriptor, valid, historyWeeks};
});
