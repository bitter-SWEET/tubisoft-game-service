# DNAS research and missing-response workflow

A missing replay packet is a research boundary, not proof that an unmodified
game cannot authenticate. Keep DNAS as a platform service, separate from the
Ubisoft accounts/lobby service. The offline workbench in
`tools/dnas_workbench.py` makes the recovered TSFP work and the GR2 investigation
repeatable without changing live packets or distributing disc material.

## Evidence and remaining work

| Layer | Evidence | Remaining boundary |
| --- | --- | --- |
| DNS and TLS | GR2 reached the local US DNAS endpoint and completed the legacy handshake | No certificate change is indicated by that attempt |
| Replay lookup | GR2 requested identity `1a8cf3f026e5d63b_01180000`; the installed store and local upstream gateway sets had no match | This describes the inspected sets, not every capture that may exist elsewhere |
| i-connect transport | The existing TSFP responder uses two nested 3DES transforms with request-derived session material | A correct transport does not establish a valid title-specific response |
| TSFP response check | Prior retail byte-flipping experiments isolated bytes `[0x3c, 0x50)` in the unwrapped response; changing that field failed while tested surrounding regions could change | Twenty bytes do not by themselves prove SHA-1 or establish its derivation; do not assume another title checks only these bytes |
| TSFP PAL outcome | An EU replay was ultimately found and used | The abandoned emulation proposal was not a completed universal generator |
| GR2 title inputs | Native code identifies its title key and a 64-KiB disc read used by DNAS initialization | Processing those inputs into an accepted response still needs tracing |
| Protected GR2 code | The workbench executes the build's two native decoder variants and recovers 116 callsite-matched protected blocks | This is code recovery for analysis, not execution of the authentication derivation |

The workbench's CBC implementation was compared byte-for-byte with the existing
TSFP DNAS responder using entirely synthetic inputs. The test suite retains the
synthetic known-answer digest and round-trip/request-binding tests. No captured
packet or title-auth value is embedded in the tools or tests. The public wire
parameter reference is [DNASrep's i-connect implementation](https://github.com/FogNo23/DNASrep/blob/master/www/dnas/us-gw/connect.php);
the workbench implements the transforms independently with standard CBC
primitives. It does not vendor the server's AGPL implementation.

## Reproduce GR2 input and code recovery

Install the optional research dependency in a local development environment:

```sh
python -m pip install -e '.[research]'
python tools/extract_gr2.py '/path/to/owned/Ghost Recon 2.iso'
python tools/dnas_workbench.py disc-input '/path/to/owned/Ghost Recon 2.iso' \
  --sector 5000 --count 32 --output work/dnas/gr2-title-auth.raw
python tools/dnas_workbench.py iop-modules work/gr2/disc/IRX/DNAS300.IMG \
  --output-directory work/dnas/gr2-iop-modules
python tools/dnas_workbench.py recover-overlay work/gr2/disc/DNAS_R.OVL \
  --profile gr2-usa --output work/dnas/gr2-decoded.raw \
  --report work/dnas/gr2-decoded-report.json
```

All output paths must be new. Files are created with mode 0600 and new output
directories with mode 0700. Keep the whole working directory private. The tool
reports lengths, hashes, module names, addresses and counts; it does not print
authentication blobs or validation-field contents.

The sector range above is specific to the examined **GR2 USA SLUS-21105** build.
Main routine `0x004c50b0` calls the native disc-read wrapper `0x00139640` with
start sector 5000, count 32 and a 2048-byte sector mode, then waits for completion.
It passes the resulting 65536-byte buffer and the eight-byte title key at
`0x00637b58` to `0x01dcfdd0` → `0x01dcf6f0`. Recovered routines `0x01dd0cc8`
and `0x01dd0dd0` copy those inputs into DNAS state at `0x01e3ecdc` and
`0x01e3ece4`. These findings identify actual inputs; they do not supply the
response's expected check value.

`DNAS_R.OVL` is a `MWo3` overlay. Import the recovered image as a raw binary at
**`0x01dce400`** with Ghidra's **`r5900:LE:32:default`** language. The first
examined routine is at `0x01dce480`. The DNAS banner is at `0x01e3e880`;
runtime BSS starts at `0x01e5ef00` with size `0x81300`. The wrapper/read code is
in the decompressed multiplayer executable imported at `0x00100000`.

The recovery profile is gated by the exact source-file SHA-256. Protected-block
metadata gives the masked length and transform parameters. Each accepted block
must also have a nearby native call to one of the build's two verified decoders,
`0x01df9af8` or `0x01e33858`; metadata-shaped tables are insufficient. The
decoder is selected from that callsite. The two variants are not interchangeable.
The decoder runs in isolated emulated memory with bounded execution. Only its
two cache-maintenance calls are stubbed; no hashing, authentication result or
validation branch is substituted. Recovered code stays private.

## Inspect and compare responses

Search every installed gateway before starting a derivation effort:

```sh
python tools/dnas_workbench.py inventory /path/to/private/dnas \
  --identity 1a8cf3f026e5d63b_01180000
```

If a private decrypted HTTP request and corresponding wire response are
available, preserve the originals and work on new files:

```sh
python tools/dnas_workbench.py identity work/dnas/request.raw
python tools/dnas_workbench.py unwrap work/dnas/request.raw work/dnas/wire.raw \
  --output work/dnas/template.raw
python tools/dnas_workbench.py wrap work/dnas/request.raw work/dnas/template.raw \
  --output work/dnas/roundtrip.raw
python tools/dnas_workbench.py compare work/dnas/template.raw work/dnas/another-template.raw
```

DNASrep replay-store records are already unwrapped templates: do not unwrap
them a second time. The codec explicitly supports the examined 328-byte
i-connect format and requires at least 308 bytes of request input; it does not
silently accept other formats. Comparisons report changed ranges and field
equality without exposing field bytes. Request files and states may include
device-specific information and remain outside publication.

An explicitly recovered 20-byte value can be placed into a private candidate:

```sh
python tools/dnas_workbench.py candidate work/dnas/template.raw \
  work/dnas/recovered-check-field.raw --output work/dnas/candidate.raw
```

This operation only places bytes. It does not derive the field, claim that GR2
uses the same layout, or install a response on a running server. It refuses
wrong sizes and existing output files. A copied value from another title is
not evidence of a valid response.

## Next validation gates

1. Trace the recovered request/response path. GR2's request builder is
   `0x01dd36b8`; response dispatcher `0x01dd5598` selects i-connect handler
   `0x01dd4f18`, which reaches `0x01dd11c0`. Disc-auth processing includes
   `0x01e34cc8`. Follow the actual data flow to the comparison and its inputs.
2. Reproduce a known captured title's expected field using its own disc input
   and native code. A transport round trip or a 20-byte output alone is not a
   sufficient check. Verify the algorithm on an independent known title/build.
3. Generate a GR2 candidate only after mapping its own checks. Test it against
   the native verifier before a retail run, then confirm the untouched game
   completes DNAS and reaches Ubisoft bootstrap. Record later DNAS requests too.
4. Keep any accepted generated response in private platform-service data with
   provenance and hashes. Publish the tools, sanitized method and synthetic
   tests; never the disc-auth data, replay payloads, console states or keys.

No missing-packet fallback or installed DNAS response was changed by this work.
GR2 authentication remains unresolved until those validation gates pass.
