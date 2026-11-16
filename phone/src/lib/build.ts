// The commit this build was made from, put in by astro.config.mjs at build
// time ("unknown" when nothing put it in, as in the tests).
declare const __KIT_BUILD_SHA__: string | undefined;
export const BUILD_SHA: string = typeof __KIT_BUILD_SHA__ === 'string' ? __KIT_BUILD_SHA__ : 'unknown';
