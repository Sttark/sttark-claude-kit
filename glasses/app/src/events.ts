// One shape for every input. A gesture can arrive as a list, text or system
// event depending on the screen and on simulator or glasses, and a tap's
// type (0) and a first row's index (0) arrive missing, because the wire
// format drops zeros. See even-g2-notes, input-events.md.
import { OsEventTypeList, type EvenHubEvent } from '@evenrealities/even_hub_sdk';

export type Input =
  | { kind: 'tap'; from: 'list' | 'text' | 'sys'; index?: number; name?: string }
  | { kind: 'double' }
  | { kind: 'up' }
  | { kind: 'down' }
  | { kind: 'foreground' }
  | { kind: 'background' }
  | { kind: 'exit' }
  /** An item of the app's own menu in the system menu (tap, then hold). */
  | { kind: 'menu'; id: number }
  | { kind: 'audio'; pcm: Uint8Array };

export function toInput(ev: EvenHubEvent): Input | null {
  if (ev.menuItemClickEvent) {
    const id = Number(ev.menuItemClickEvent.itemID);
    return id > 0 ? { kind: 'menu', id } : null;
  }
  if (ev.audioEvent) {
    const pcm = ev.audioEvent.audioPcm;
    return pcm && pcm.length ? { kind: 'audio', pcm } : null;
  }
  if (ev.listEvent) {
    const t = ev.listEvent.eventType ?? OsEventTypeList.CLICK_EVENT;
    if (t === OsEventTypeList.CLICK_EVENT) {
      return {
        kind: 'tap',
        from: 'list',
        index: ev.listEvent.currentSelectItemIndex ?? undefined,
        name: ev.listEvent.currentSelectItemName ?? undefined,
      };
    }
    if (t === OsEventTypeList.DOUBLE_CLICK_EVENT) return { kind: 'double' };
    return null; // a list scrolls itself; its edge events mean nothing here
  }
  if (ev.textEvent) {
    const t = ev.textEvent.eventType ?? OsEventTypeList.CLICK_EVENT;
    if (t === OsEventTypeList.SCROLL_TOP_EVENT) return { kind: 'up' };
    if (t === OsEventTypeList.SCROLL_BOTTOM_EVENT) return { kind: 'down' };
    if (t === OsEventTypeList.DOUBLE_CLICK_EVENT) return { kind: 'double' };
    if (t === OsEventTypeList.CLICK_EVENT) return { kind: 'tap', from: 'text' };
    return null;
  }
  if (ev.sysEvent) {
    if (ev.sysEvent.imuData) return null;
    const t = ev.sysEvent.eventType ?? OsEventTypeList.CLICK_EVENT;
    switch (t) {
      case OsEventTypeList.CLICK_EVENT:
        return { kind: 'tap', from: 'sys' };
      case OsEventTypeList.DOUBLE_CLICK_EVENT:
        return { kind: 'double' };
      case OsEventTypeList.FOREGROUND_ENTER_EVENT:
        return { kind: 'foreground' };
      case OsEventTypeList.FOREGROUND_EXIT_EVENT:
        return { kind: 'background' };
      case OsEventTypeList.ABNORMAL_EXIT_EVENT:
      case OsEventTypeList.SYSTEM_EXIT_EVENT:
        return { kind: 'exit' };
      default:
        return null; // long press belongs to the system menu; IMU is unused
    }
  }
  return null;
}
