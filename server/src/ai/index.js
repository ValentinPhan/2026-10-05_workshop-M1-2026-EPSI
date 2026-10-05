import { createMockAnalyzer } from './mockAnalyzer.js';
import { createHttpAnalyzer } from './httpAnalyzer.js';

export function createAnalyzer(config) {
  switch (config.analyzer) {
    case 'mock':
      return createMockAnalyzer();
    case 'http':
      return createHttpAnalyzer({ url: config.aiUrl, timeoutMs: config.aiTimeoutMs });
    default:
      throw new Error(`ANALYZER inconnu : ${config.analyzer} (mock | http)`);
  }
}
