// Shared by the server's filtered event proxy and browser; no SDK is required.
export async function* readEvents(body) {
  const reader = body.getReader(), decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      if (buffer.length > 1024 * 1024) throw new Error('Event exceeded the stream limit.');
      let match;
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, match.index); buffer = buffer.slice(match.index + match[0].length);
        const data = frame.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, '')).join('\n');
        if (data && data !== '[DONE]') yield JSON.parse(data);
      }
      if (done) break;
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
