# IMG metadata decoder derived from NoLifeWzToNx

This directory retains the original IMG decoding and reference-resolution core from
[ryantpayton/NoLifeWzToNx](https://github.com/ryantpayton/NoLifeWzToNx), with source
revision and local adaptations recorded in [UPSTREAM.json](../UPSTREAM.json).
The upstream project name and directory are retained for provenance.

## Local scope

- Decode the BeiDou client's original read-only `Data/**/*.img` into metadata trees.
- Preserve strings, numeric properties, vectors, Canvas dimensions, source order,
  source files and UOL / `source` / `_outlink` / `_inlink` resolution.
- Leave missing or unresolved resources unknown; do not substitute another format.
- Do not decode playable audio or drawable pixel buffers.

The WZ container parser, NX serializer and converter command-line entry point have
been removed. There is no WZ-to-NX conversion command or output artifact in this
fork. Historical upstream conversion instructions do not apply.

## Integration

[ImgResources.cpp](../../headless/src/ImgResources.cpp) embeds this core and exposes
an independent C ABI. Python loads the library in its own process; the headless
adapter builds its in-memory node view from the same decoder. Neither reader
requires a running GUI client or a GUI bridge DLL.

Build the standalone library from the repository root:

```bash
make -C headless build/libbeidou-img.so
```

[Keys.cpp](Keys.cpp) retains the upstream string key tables. Compression and image
rendering libraries are not required by this metadata-only core.

## License

GNU Affero General Public License v3.0 or later; see the retained source headers.

Copyright &copy; 2014–2020 Peter Atashian, Ryan Payton.
