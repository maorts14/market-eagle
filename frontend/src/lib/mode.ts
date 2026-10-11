export const syntheticApiTest = import.meta.env.VITE_SYNTHETIC_API_TEST === '1'
export const explorerMode = syntheticApiTest || import.meta.env.VITE_EXPLORER_MODE === 'api' ? 'api' : 'fixture'
export const agentMode = syntheticApiTest || import.meta.env.VITE_AGENT_MODE === 'api' ? 'api' : 'fixture'

export function isSyntheticTestData(data: { synthetic: boolean; source: string }) {
  return data.synthetic && data.source === 'synthetic-v1'
}
