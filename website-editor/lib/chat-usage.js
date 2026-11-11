const empty = () => ({ model_requests: 0, reported_responses: 0, input_tokens: 0, cached_input_tokens: 0, output_tokens: 0, containers: 0 });
export function usageEvent(chat, key, value = 1) {
  chat.usage ||= empty(); chat.run.usage ||= empty();
  chat.usage[key] = (chat.usage[key] || 0) + value;
  chat.run.usage[key] = (chat.run.usage[key] || 0) + value;
}
export function recordUsage(chat, response) {
  chat.run.accountedResponses ||= [];
  const id = response.id || chat.run.responseId;
  if (chat.run.accountedResponses.includes(id)) return;
  chat.run.accountedResponses.push(id);
  // Reserve the full allowance if a provider omits usage, rather than letting
  // an incomplete usage report bypass the per-message output limit.
  const output = response.usage?.output_tokens;
  chat.run.outputBudgetUsed = (chat.run.outputBudgetUsed || 0) + (Number.isSafeInteger(output) && output >= 0 ? output : chat.run.outputAllowance || 0);
  if (!response.usage) return;
  usageEvent(chat, 'reported_responses');
  for (const [key, value] of Object.entries({ input_tokens: response.usage.input_tokens, cached_input_tokens: response.usage.input_tokens_details?.cached_tokens, output_tokens: response.usage.output_tokens })) {
    if (Number.isSafeInteger(value) && value >= 0) usageEvent(chat, key, value);
  }
}
