# Third-party code

## blackbox-mod / JOEBOX (Justin Joe)

[j3threejay/blackbox-mod](https://github.com/j3threejay/blackbox-mod), MIT licence. This repository does **not**
contain its sources: the builds export a pinned commit from your own clone (`repos/blackbox-mod`, see `setup.sh`),
apply small scripted edits listed in `bb/joebox/build.py` (`SSL_EDITS`: a ninth compressor model, its page, and the
matching expectation in its `test_comp.py`), and compile it together with ours. The BL encoder in
`patches/thumb.py` is ported from it. Several hook sites and addresses follow its findings, credited where used.

```
MIT License

Copyright (c) 2026 Justin Joe

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

Built images contain JOEBOX code; when you share a built image, its MIT notice applies to that part. Built images
also contain 1010music's firmware, which you may not be allowed to redistribute: share the build instructions, not
the images.

## 1010music firmware

Not included and not licensed here. The build needs your own copy of the stock `BLACKBOX.bin` 3.1.9 in `firmware/`.
