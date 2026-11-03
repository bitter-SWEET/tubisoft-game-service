# XIII Ubisoft key exchange

This note covers the game service after bootstrap. Sony DNAS is outside the current work. Addresses refer to the US PS2 network overlay mapped at `0x01cee500` and the main ELF identified in [the disc notes](xiii-ps2-network.md). Static findings are supplemented by a local, unmodified XIII client session: the client accepted the lab's generated key, exchanged keys, and sent account and login requests that the lab decoded.

## What the client constructs

`0x01d63350` initializes the crypto context. On its encrypted mode path it calls `0x01d63920` with `0x10`, which allocates and generates **16 bytes** of session-key material. It calls `0x01d3ec90` with selector 0 and those key bytes. That wrapper calls `0x01d3f580`, which dispatches selector 0 to constructor `0x01d427b0`. The constructor installs vtable `0x00413e50`; its type descriptor at `0x01d9dd30` points to the string `CipherModule_Blowfish`. This is a direct chain from the generated key to the Blowfish implementation, rather than merely an algorithm name in the binary.

The same initialization path creates selector 1 via `0x01d3ec90`; `0x01d3f580` dispatches it to `0x01d42bf0`, vtable `0x00413e20`, type descriptor `0x01d9dce0`, and string `CipherModule_GSXor`. The RSA module comes from `0x01d3ed20` → `0x01d3fc00` → `0x01d42ec0`, vtable `0x00413e70`, type descriptor `0x01d9dda0`, string `PKCModule_RSA`.

Initialization also generates a local public/private key pair: `0x01d639c0` logs `GenerateGlobalKeyPair()` and calls the public-key module. The code writes `0x200` into the key structure before that call. The generator at `0x01d46ff0` interprets this as the RSA bit count, selects exponent 3 when the next field is zero, and accepts bit counts from 508 through 1024. The client initializes this field to zero, giving a 512-bit key with exponent 3 in this path. `0x01d63740` copies `0x104` bytes of local public-key data, and `0x01d61f50` sends that data in key-exchange message `0xdb` with subtype 1.

## Public-key and encrypted payload formats

`0x01d46ff0` writes the public key as a native little-endian 32-bit bit count followed by 128 bytes of modulus and 128 bytes of public exponent. `0x01d48720` encodes each integer big-endian in its fixed-width field. The entire structure is 260 bytes. The public-key operation `0x01d473f0` constructs a `00 02` block with nonzero random padding and a zero separator before the payload; `0x01d477d0` recognizes that block on private-key decryption. This is RSA PKCS #1 v1.5 encryption padding. The lab and client exchanged keys in this format; the [independent GS implementation](https://github.com/michal-kapala/ubi-gs/blob/master/pkc.py) provides comparison evidence from another game.

The Blowfish encryption wrapper at `0x01d42960` zero-pads the plaintext to a multiple of eight bytes, encrypts each block separately with `0x01d468b0`, and appends the unencrypted original length as a two-byte little-endian integer. Aligned inputs do not receive an extra padding block; plaintext is limited to 65535 bytes. `0x01d42ab0` reads that trailer and applies the inverse operation. Each 32-bit half is read and written in the PS2's little-endian order; a conventional big-endian Blowfish library needs each four-byte word reversed before and after the block operation. There is no chaining between blocks in these functions. The independent [GS Blowfish implementation](https://github.com/michal-kapala/ubi-gs/blob/master/blowfish.py) corroborates the overall format, but its decrypt routine currently multiplies the high length byte by 16. The XIII client reads a native 16-bit value, so use a base-256 little-endian length.

The ordinary GS XOR path is also visible in XIII: `0x01d46f20` XORs each byte with `(position + 0x89) & 0xff`; `0x01d46bd0` and `0x01d46d30` apply and reverse a diagonal grid permutation using a side length of `ceil(sqrt(payload_length))`. This is obfuscation without a secret key. `src/ubisoft/gsxor.py` implements the observed transform with a local 65535-byte resource cap.

Experimental implementations are in `src/ubisoft/crypto.py`; the GS header parser is in `src/ubisoft/frame.py`. The bounded `src/ubisoft/data.py` implements a subset of the client data serializer: `s` for NUL-terminated strings, `b` for binary values with a big-endian 32-bit length, and bracketed nested lists. The outer list is unbracketed. The tag constants and serializers are at `0x01d56460`, `0x01d566a0`, and `0x01d56830`; other tags remain unimplemented. The lab decoded actual XIII account and login requests using the client-generated Blowfish key, and XIII accepted several ordinary GS replies; this does not validate all message types, payload sizes, or the reverse encrypted direction. A cryptographic library must support legacy 512-bit RSA and Blowfish for this interoperability path.

## What happens when keys arrive

* `0x01d62060` dispatches key-exchange subtypes 1, 2, and 3. The dispatch invokes `0x01d62260` for a received public-key message and `0x01d62380` for a received cipher-key message.
* In the public-key handler `0x01d62260`, the incoming key bytes are passed to `0x01d63580` along with the context's generated session-key bytes. Its result is passed to `0x01d62630`, which sends a cipher-key message. The function does not itself perform an obvious certificate-chain check or compare the received key with a hard-coded key. Lower-level routines still need to be checked before concluding that arbitrary keys are accepted.
* The cipher-key handler `0x01d62380` calls `0x01d63600` to process the received key material and `0x01d63770` to install the result as a cipher key. Both handlers set the exchange-completion flag after their respective operation. Determine the role of each context and the direction of each key from the connection setup and a live exchange before implementing the server side.
* Login message `0x66` is assembled in `0x01d6acc0`. It goes through `0x01d8a9a0` and `0x01d61890`, which requires an exchange-completion flag and constructs an encrypted message with property 2 using `0x01d5ea30`. A plaintext success response alone is not a substitute for a functioning encrypted login path.

This handshake uses public-key and cipher-key messages. We have not found an X.509 certificate check in the traced Ubisoft path; that is not proof that there is no server identity or public-key validation elsewhere. Bootstrap itself is ordinary HTTP. The US client accepted the lab's locally generated RSA pair for the tested account, router and launcher connections; that observation does not establish behavior for other disc versions or services.

## Remaining work

1. Check remaining public-key handler callees for identity checks and test encrypted server-to-client messages, boundary lengths and alternate disc versions.
2. Recover XIII-specific lobby and room data independently from the shared message, cipher, router, wait-module and NAT machinery. Validate a second title's dialect before claiming the machinery is universal.
3. Keep traces bounded and private: retain message metadata and state transitions without recording credentials, keys or decrypted account payloads.

The broader [workflow and host/join map](xiii-online-workflow.md) records the message framing and callback addresses.
