import { createMockProvider } from './mockProvider.js';
import { createSshProvider } from './sshProvider.js';

export function createProvider(config) {
  switch (config.provider) {
    case 'mock':
      return createMockProvider({ tickMs: config.tickMs });
    case 'ssh':
      return createSshProvider(config.ssh, { tickMs: config.tickMs });
    default:
      throw new Error(`PROVIDER inconnu : ${config.provider} (mock | ssh)`);
  }
}
