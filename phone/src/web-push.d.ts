// The part of web-push (4.x, which ships no types) that lib/push.ts uses.
declare module 'web-push' {
  export type PushSubscription = { endpoint: string; keys: { p256dh: string; auth: string } };
  export type RequestOptions = {
    vapidDetails?: { subject: string; publicKey: string; privateKey: string };
    TTL?: number;
    urgency?: 'very-low' | 'low' | 'normal' | 'high';
    topic?: string;
    headers?: Record<string, string>;
    timeout?: number;
  };
  export type RequestDetails = { method: 'POST'; headers: Record<string, string | number>; body: Buffer | null; endpoint: string };
  export function generateVAPIDKeys(): { publicKey: string; privateKey: string };
  export function generateRequestDetails(subscription: PushSubscription, payload?: string | Buffer | null, options?: RequestOptions): RequestDetails;
}
