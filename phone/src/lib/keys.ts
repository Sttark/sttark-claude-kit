// A Mac's key and the tokens of linking. Each Mac makes its own P-256
// signing key (in the Secure Enclave where it can) and sends only the
// public half, as SPKI (DER, base64), when it asks to link. On each
// connection it signs the server's challenge; the server keeps only public
// keys, so a copy of its database cannot pose as a Mac.
import { createHash, createPublicKey, randomBytes, randomInt, verify } from 'node:crypto';

/** What a Mac signs on each connection: UTF-8 of these three lines, with no
 *  newline at the end. The Mac id and the nonce never hold a newline (their
 *  patterns in schema/messages.v1.json). */
export function signedText(macId: string, nonce: string): string {
  return `kit-mac-v1\n${macId}\n${nonce}`;
}

/** The public key as the server keeps it (SPKI DER, base64), or null when
 *  it is not a P-256 public key. */
export function parseMacKey(b64: string): string | null {
  try {
    const der = Buffer.from(b64, 'base64');
    const key = createPublicKey({ key: der, format: 'der', type: 'spki' });
    if (key.asymmetricKeyType !== 'ec' || key.asymmetricKeyDetails?.namedCurve !== 'prime256v1') return null;
    return key.export({ format: 'der', type: 'spki' }).toString('base64');
  } catch {
    return null;
  }
}

/** Checks a Mac's signature of signedText(macId, nonce): ECDSA with SHA-256,
 *  base64 (or base64url), either DER (X9.62, what SecKeyCreateSignature and
 *  CryptoKit's derRepresentation give) or the 64-byte r and s
 *  (rawRepresentation). */
export function verifyMacSignature(publicKeyB64: string, macId: string, nonce: string, sigB64: string): boolean {
  let key;
  try {
    key = createPublicKey({ key: Buffer.from(publicKeyB64, 'base64'), format: 'der', type: 'spki' });
  } catch {
    return false;
  }
  const sig = Buffer.from(sigB64, 'base64');
  const data = Buffer.from(signedText(macId, nonce), 'utf8');
  const check = (dsaEncoding: 'der' | 'ieee-p1363') => {
    try {
      return verify('sha256', data, { key, dsaEncoding }, sig);
    } catch {
      return false;
    }
  };
  // 64 bytes is almost always r and s; a DER signature of that length is
  // rare but possible, so it is tried too.
  return sig.length === 64 ? check('ieee-p1363') || check('der') : check('der');
}

/** A random 256-bit token, base64url (43 characters): a link page's
 *  address and the Kit's poll. */
export const newToken = (): string => randomBytes(32).toString('base64url');

/** The challenge's nonce: 192 random bits, base64url (32 characters). */
export const newNonce = (): string => randomBytes(24).toString('base64url');

/** The database keeps only this hash of a token. */
export const tokenHash = (token: string): string => createHash('sha256').update(token, 'utf8').digest('hex');

/** Four capital letters, without I and O, which read like 1 and 0. */
const LETTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ';
export function newCode(): string {
  let s = '';
  for (let i = 0; i < 4; i++) s += LETTERS[randomInt(LETTERS.length)];
  return s;
}
