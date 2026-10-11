import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules() })

describe('synthetic API test mode', () => {
  it('selects both real API adapters from one explicit flag', async () => {
    vi.stubEnv('VITE_SYNTHETIC_API_TEST', '1')
    const mode = await import('./mode')

    expect(mode.syntheticApiTest).toBe(true)
    expect(mode.explorerMode).toBe('api')
    expect(mode.agentMode).toBe('api')
    expect(mode.isSyntheticTestData({ synthetic: true, source: 'synthetic-v1' })).toBe(true)
    expect(mode.isSyntheticTestData({ synthetic: false, source: 'alpaca' })).toBe(false)
  })

  it('keeps the ordinary frontend modes when the flag is absent', async () => {
    vi.stubEnv('VITE_SYNTHETIC_API_TEST', '')
    vi.stubEnv('VITE_EXPLORER_MODE', 'api')
    vi.stubEnv('VITE_AGENT_MODE', 'fixture')
    const mode = await import('./mode')

    expect(mode.syntheticApiTest).toBe(false)
    expect(mode.explorerMode).toBe('api')
    expect(mode.agentMode).toBe('fixture')
  })
})
