# Third-party notices

wasp-mcp incorporates or builds upon the following third-party work. This file
must accompany any distribution of the software, including standalone
distribution of the compiled `GH_MCP_Wasp.gha` (e.g. via Yak / Food4Rhino).

## grasshopper-mcp (MIT)

`GH_MCP_Wasp/` is a fork of the `GH_MCP` component from
[grasshopper-mcp](https://github.com/alfredatnycu/grasshopper-mcp), vendored
read-only under `vendor/grasshopper-mcp/`.

```
MIT License

Copyright (c) 2025 Alfred Chen

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Wasp (LGPL-3.0) — not distributed

[Wasp](https://github.com/ar0551/Wasp) by Andrea Rossi is NOT distributed with
wasp-mcp. Users install Wasp themselves; wasp-mcp instantiates the
user-installed `.ghuser` UserObjects at runtime via Grasshopper's public API.
`server/knowledge/wasp_patterns.json` records factual observations (parameter
names, wiring topology, slider values) derived from Wasp's example files; see
`docs/licensing-audit.md` for the licensing analysis.

## Architectural corpus sources — not distributed

The repositories mined under `corpus/arch/` are recorded with URLs and
licenses in `corpus/ARCH_SOURCES.md`. The `corpus/` directory is a local
research asset and is excluded from every distribution artifact. Attribution
for CC BY-SA sources (ParametricCamp, Jose Luis García del Castillo y López)
applies to the derived `arch_patterns.json` / `arch_component_kb.json`; see
`docs/licensing-audit.md`.

## Rhino / Grasshopper SDK

RhinoCommon and the Grasshopper SDK are used under McNeel's developer terms;
RhinoCommon is MIT-licensed. `GH_IO.dll` and other McNeel assemblies are
referenced, never redistributed.
