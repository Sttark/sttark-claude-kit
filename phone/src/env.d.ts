/// <reference types="astro/client" />
declare namespace App {
  interface Locals {
    /** Who is signed in (lib/session.ts), or DEV_FAKE_USER on a local run. */
    user: { email: string; name: string } | null;
  }
}
