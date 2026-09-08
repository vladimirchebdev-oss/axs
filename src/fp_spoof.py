"""Подмена Canvas / WebGL / AudioContext.

Включается только при SPOOF_FP=1. На headed+Xvfb держим 0:
хуки раньше ломали тихий Turnstile.
"""

from __future__ import annotations

# Linux-совместимые строки: не D3D11/Windows при UA X11.
_SCRIPT = r"""
(() => {
  if (window.__axsFp) return;
  window.__axsFp = 1;

  const VENDOR = 'Google Inc. (Intel)';
  const RENDERER = 'ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)';

  const patchGl = (proto) => {
    if (!proto || proto.getParameter.__axs) return;
    const orig = proto.getParameter;
    const wrapped = function (p) {
      if (p === 37445) return VENDOR;
      if (p === 37446) return RENDERER;
      return orig.apply(this, arguments);
    };
    wrapped.__axs = 1;
    proto.getParameter = wrapped;
  };
  patchGl(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
  patchGl(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);

  const bump = (canvas) => {
    try {
      const ctx = canvas.getContext('2d');
      if (!ctx || !canvas.width || !canvas.height) return;
      const pix = ctx.getImageData(0, 0, 1, 1);
      pix.data[3] = pix.data[3] ^ 1;
      ctx.putImageData(pix, 0, 0);
    } catch (e) {}
  };
  const toData = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function () {
    bump(this);
    return toData.apply(this, arguments);
  };
  const toBlob = HTMLCanvasElement.prototype.toBlob;
  if (toBlob) {
    HTMLCanvasElement.prototype.toBlob = function () {
      bump(this);
      return toBlob.apply(this, arguments);
    };
  }

  const seen = new WeakSet();
  const channel = AudioBuffer.prototype.getChannelData;
  AudioBuffer.prototype.getChannelData = function () {
    const data = channel.apply(this, arguments);
    if (data && data.length && !seen.has(data)) {
      seen.add(data);
      try { data[0] += 1e-7; } catch (e) {}
    }
    return data;
  };
})();
"""


async def apply_fp_spoof(tab) -> None:
    import nodriver as uc

    await tab.send(uc.cdp.page.add_script_to_evaluate_on_new_document(source=_SCRIPT))
    try:
        await tab.evaluate(_SCRIPT, return_by_value=True)
    except Exception:
        pass
