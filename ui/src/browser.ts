import type { App } from '@modelcontextprotocol/ext-apps';

// Only the host capabilities used by the existing renderer belong here. Both
// the SDK and HTTP adapter are checked against this contract by TypeScript.
export type PanelApp = Pick<App, 'ontoolresult' | 'onhostcontextchanged' | 'onteardown' | 'onclose'
  | 'connect' | 'callServerTool' | 'getHostContext' | 'requestDisplayMode' | 'close'>;

/** The standalone page uses the same renderer, gestures and toolbar as the MCP app. */
export class BrowserApp implements PanelApp {
  ontoolresult: App['ontoolresult'];
  onhostcontextchanged: App['onhostcontextchanged'];
  onteardown: App['onteardown'];
  onclose: App['onclose'];
  private base: string;
  private token: string;

  constructor() {
    this.base = new URL('.', window.location.href).pathname;
    this.token = this.base.split('/').filter(Boolean)[0] ?? '';
  }

  async connect(_transport?: Parameters<App['connect']>[0], options?: Parameters<App['connect']>[1]) {
    const data = await this.request('health', {}, options?.timeout ?? 3000);
    if (data.app !== 'iphone-use-browser') throw new Error('手机网页服务不可用');
  }

  private async request(path: string, options: RequestInit, timeout: number) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(this.base + path, { ...options, cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error('手机网页请求失败');
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  }

  // Use a property rather than another SDK-shaped method: host adapters hook the
  // single MCP SDK callServerTool method in the self-contained bundle.
  callServerTool: App['callServerTool'] = async (call, options) =>
    this.request('api', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this.token },
      body: JSON.stringify(call),
    }, options?.timeout ?? 3000);

  getHostContext(): ReturnType<App['getHostContext']> {
    return { displayMode: 'fullscreen', availableDisplayModes: [] };
  }

  async requestDisplayMode() { return { mode: 'fullscreen' as const }; }
  async close() { this.onclose?.(); }
}
