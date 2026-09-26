import type { Locator, Page } from 'playwright';

// Drawn into the page so the journey video shows which step is running and
// what it acts on. Screenshots hide it (SCREENSHOT_STYLE): the judge must see
// the product as a user does, without our annotations.
const ID = '__uxaudit_overlay';
export const SCREENSHOT_STYLE = `#${ID}{display:none!important}`;

/** How long the video lingers on the annotation before the action runs. */
export const ANNOTATE_MS = 450;

export interface Point {
  x: number;
  y: number;
}

/** Show the step caption, outline the target, and glide the cursor to it.
 *  Returns the cursor position for the next step. Never throws: a missing
 *  target is the step's failure to report, not the overlay's. */
export async function annotate(page: Page, index: number, label: string, target: Locator | undefined, from: Point): Promise<Point> {
  let box: { x: number; y: number; width: number; height: number } | null = null;
  if (target) {
    try {
      await target.scrollIntoViewIfNeeded({ timeout: 2_000 });
      box = await target.boundingBox({ timeout: 1_000 });
    } catch {
      box = null;
    }
  }
  await page
    .evaluate(
      ({ id, text, box, from }) => {
        document.getElementById(id)?.remove();
        const root = document.createElement('div');
        root.id = id;
        root.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483647;font:600 16px/1.35 system-ui,sans-serif';
        const cap = document.createElement('div');
        cap.textContent = text;
        cap.style.cssText =
          'position:absolute;left:50%;top:10px;transform:translateX(-50%);max-width:92%;padding:6px 12px;border-radius:6px;' +
          'background:rgba(15,23,42,.9);color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
        root.append(cap);
        if (box) {
          const ring = document.createElement('div');
          ring.style.cssText =
            `position:absolute;left:${box.x - 4}px;top:${box.y - 4}px;width:${box.width + 8}px;height:${box.height + 8}px;` +
            'border:3px solid #f59e0b;border-radius:6px;box-sizing:border-box';
          const cursor = document.createElement('div');
          cursor.dataset.role = 'cursor';
          cursor.style.cssText =
            `position:absolute;left:${from.x}px;top:${from.y}px;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;` +
            'background:rgba(15,23,42,.85);border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);transition:left .35s ease,top .35s ease';
          root.append(ring, cursor);
          document.documentElement.append(root);
          requestAnimationFrame(() => {
            cursor.style.left = `${box.x + box.width / 2}px`;
            cursor.style.top = `${box.y + box.height / 2}px`;
          });
        } else {
          document.documentElement.append(root);
        }
      },
      { id: ID, text: `${String(index).padStart(2, '0')} · ${label}`, box, from },
    )
    .catch(() => {});
  await page.waitForTimeout(ANNOTATE_MS);
  return box ? { x: box.x + box.width / 2, y: box.y + box.height / 2 } : from;
}

/** A ripple where the click landed. The page may already have navigated
 *  away, in which case there is nothing to draw on. */
export async function ripple(page: Page, at: Point) {
  await page
    .evaluate(
      ({ id, at }) => {
        const root = document.getElementById(id);
        if (!root) return;
        const r = document.createElement('div');
        r.style.cssText =
          `position:absolute;left:${at.x}px;top:${at.y}px;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;` +
          'border:3px solid #f59e0b;opacity:1;transform:scale(.3);transition:transform .45s ease-out,opacity .45s ease-out';
        root.append(r);
        requestAnimationFrame(() => {
          r.style.transform = 'scale(1.4)';
          r.style.opacity = '0';
        });
      },
      { id: ID, at },
    )
    .catch(() => {});
}
