import type { Disposable, Page } from 'playwright';

// Narrates the journey video with Playwright's screencast decorations: its
// animated cursor and target highlight, plus our own step caption. Overlays
// persist across navigations. Screenshots for the judge hide all of them:
// the judge must see the product as a user does.

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

// Bottom-left: navigation sits at the top and toasts usually appear
// bottom-centre or top-right, so this corner hides the least.
const CAPTION_STYLE =
  'position:fixed;bottom:12px;left:12px;max-width:60%;padding:6px 12px;border-radius:6px;background:rgba(15,23,42,.85);color:#fff;' +
  'font:600 16px/1.35 system-ui,sans-serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';

export class Narration {
  private actions: Disposable | undefined;
  private captionOverlay: Disposable | undefined;

  constructor(private readonly page: Page) {}

  async start(path: string, size: { width: number; height: number }) {
    await this.page.screencast.start({ path, size });
    await this.showActions();
  }

  /** Playwright titles actions with their raw values (`Fill "…"`), so turn
   *  the decorations off around steps that type a secret. */
  async showActions() {
    this.actions ??= await this.page.screencast.showActions({ cursor: 'pointer', position: 'top-right', fontSize: 16, duration: 450 });
  }

  async hideActions() {
    await this.actions?.dispose();
    this.actions = undefined;
  }

  async caption(text: string) {
    await this.captionOverlay?.dispose();
    this.captionOverlay = await this.page.screencast.showOverlay(`<div style="${CAPTION_STYLE}">${esc(text)}</div>`);
  }

  async stop() {
    await this.page.screencast.stop();
  }
}

/** A screenshot without any narration overlays. */
export async function cleanScreenshot(page: Page): Promise<Buffer> {
  await page.screencast.hideOverlays().catch(() => {});
  try {
    return await page.screenshot({ type: 'jpeg', quality: 72 });
  } finally {
    await page.screencast.showOverlays().catch(() => {});
  }
}
