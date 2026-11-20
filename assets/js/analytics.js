// Only the public website sends page views. Local and embedded previews do not.
(() => {
  const token = document.currentScript?.dataset.beaconToken;
  if (!/^[a-f0-9]{32}$/i.test(token || '') || location.protocol !== 'https:' ||
      !['nateoconnell.com', 'www.nateoconnell.com'].includes(location.hostname) || window.top !== window.self ||
      location.pathname === '/login/' || location.pathname === '/login') return;
  if (navigator.doNotTrack === '1' || navigator.globalPrivacyControl === true) return;
  const script = document.createElement('script');
  script.type = 'module';
  script.src = 'https://static.cloudflareinsights.com/beacon.min.js';
  script.dataset.cfBeacon = JSON.stringify({ token });
  document.head.append(script);
})();
