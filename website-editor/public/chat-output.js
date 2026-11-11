// Keep stream fragments separate from saved snapshots. A reconnect can start
// halfway through a message; appending that suffix to a snapshot duplicates text.
export class ChatOutput {
  constructor() { this.items = new Map(); }
  snapshot(messages) {
    for (const message of messages || []) {
      if (!message.id) continue;
      const item = this.items.get(message.id) || { id: message.id, parts: new Map() };
      item.saved = message.content; item.phase = message.phase;
      if (message.status === 'completed') item.finished = message.content;
      this.items.set(message.id, item);
    }
    const order = [...(messages || []).map(message => message.id), ...this.items.keys()];
    this.items = new Map([...new Set(order)].filter(id => this.items.has(id)).map(id => [id, this.items.get(id)]));
  }
  event(event) {
    if (event.kind === 'message') {
      const item = this.items.get(event.id) || { id: event.id, parts: new Map() };
      item.finished = event.content; item.phase = event.phase; this.items.set(event.id, item); return;
    }
    if (event.kind !== 'text') return;
    const item = this.items.get(event.id) || { id: event.id, parts: new Map() };
    const part = item.parts.get(event.part) || { text: '', done: false };
    if (event.replace) { part.text = event.text; part.done = true; }
    else if (!part.done) part.text = (part.text + event.text).slice(0, 20000);
    item.parts.set(event.part, part); this.items.set(event.id, item);
  }
  messages() {
    return [...this.items.values()].slice(-24).map(item => {
      const parts = [...item.parts].sort(([a], [b]) => a - b).map(([, part]) => part);
      const streamed = parts.map(part => part.text).join('\n'), saved = item.saved || '';
      const sameStart = streamed.startsWith(saved.slice(0, 40)) || saved.startsWith(streamed);
      const content = item.finished ?? (parts.length && parts.every(part => part.done) ? streamed : !saved || sameStart && streamed.length > saved.length ? streamed : saved);
      return { id: item.id, phase: item.phase, content };
    }).filter(item => item.content);
  }
}
