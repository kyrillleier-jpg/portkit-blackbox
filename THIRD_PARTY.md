# Third-party code

## blackbox-mod (Justin Joe)

`src/filter.c` and the BL encoder in `patches/thumb.py` are ported from
[j3threejay/blackbox-mod](https://github.com/j3threejay/blackbox-mod) (Blackbox 3.1.9), MIT licence:

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

## stmlib (Emilie Gillet)

The state-variable filter in `src/filter.c` follows `stmlib/dsp/filter.h` (class `Svf`), Copyright 2014 Emilie Gillet,
MIT licence.

## 1010music firmware

Not included and not licensed here. The patcher needs your own copy of the stock `MICRO.BIN` 2.3.4 in `firmware/`.
