# Third-party notices

## OpenCodex

This repository includes copied and modified source files from
[OpenCodex](https://github.com/lidge-jun/opencodex), version `2.60.0`.
The files are kept under `.opencodex-patch/`:

- `main-account-probe.ts`
- `pool-quota-probe.ts`
- `reset-credit-details-cache.ts`
- `original/main-account-probe.ts`
- `original/pool-quota-probe.ts`
- `original/reset-credit-details-cache.ts`

The files under `original/` preserve the upstream source used for comparison
and rollback. The files at the top level of `.opencodex-patch/` contain local
modifications that connect OpenCodex's reset-credit-details cache to this
widget workflow. These files are not original work of this repository.

The copied and modified OpenCodex files remain subject to the following MIT
License. The upstream copyright and license notices must be retained in any
copy or substantial portion of those files.

### Upstream MIT License

MIT License

Copyright (c) 2026 opencodex contributors

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
