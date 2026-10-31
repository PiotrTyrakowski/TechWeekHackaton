/*
 * Silver dither background — dependency-free WebGL2 fullscreen shader.
 * The wave pass and the Bayer-quantize pass
 * are merged into one fragment shader: the wave is evaluated at the snapped
 * pixel-block coordinate, quantized, and mapped onto the 4-stop silver ramp.
 *
 * Parameters: ramp DITHER_RAMP_LIGHT, wave speed 0.0805, frequency 3, amplitude 0.3,
 * 4 levels, pixel size 2 (≥1024px) / 3, DPR fixed at 1, no mouse interaction.
 */
(() => {
  "use strict";

  const RAMP = ["#fafaf9", "#eaeae7", "#d9d9d4", "#c9c9c4"];
  const GRAIN_OPACITY = 0.05;
  // Frozen frame shown under prefers-reduced-motion — an arbitrary but fixed
  // moment of the drift, chosen so the field isn't the t=0 degenerate frame.
  const STATIC_TIME = 12.0;

  const VERT = `#version 300 es
in vec2 position;
void main() { gl_Position = vec4(position, 0.0, 1.0); }
`;

  const FRAG = `#version 300 es
precision highp float;
uniform vec2 resolution;
uniform float time;
uniform float pixelSize;
uniform vec3 ramp0;
uniform vec3 ramp1;
uniform vec3 ramp2;
uniform vec3 ramp3;
out vec4 fragColor;

vec4 mod289(vec4 x) { return x - floor(x * (1.0/289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
vec2 fade(vec2 t) { return t*t*t*(t*(t*6.0-15.0)+10.0); }

float cnoise(vec2 P) {
  vec4 Pi = floor(P.xyxy) + vec4(0.0,0.0,1.0,1.0);
  vec4 Pf = fract(P.xyxy) - vec4(0.0,0.0,1.0,1.0);
  Pi = mod289(Pi);
  vec4 ix = Pi.xzxz;
  vec4 iy = Pi.yyww;
  vec4 fx = Pf.xzxz;
  vec4 fy = Pf.yyww;
  vec4 i = permute(permute(ix) + iy);
  vec4 gx = fract(i * (1.0/41.0)) * 2.0 - 1.0;
  vec4 gy = abs(gx) - 0.5;
  vec4 tx = floor(gx + 0.5);
  gx = gx - tx;
  vec2 g00 = vec2(gx.x, gy.x);
  vec2 g10 = vec2(gx.y, gy.y);
  vec2 g01 = vec2(gx.z, gy.z);
  vec2 g11 = vec2(gx.w, gy.w);
  vec4 norm = taylorInvSqrt(vec4(dot(g00,g00), dot(g01,g01), dot(g10,g10), dot(g11,g11)));
  g00 *= norm.x; g01 *= norm.y; g10 *= norm.z; g11 *= norm.w;
  float n00 = dot(g00, vec2(fx.x, fy.x));
  float n10 = dot(g10, vec2(fx.y, fy.y));
  float n01 = dot(g01, vec2(fx.z, fy.z));
  float n11 = dot(g11, vec2(fx.w, fy.w));
  vec2 fade_xy = fade(Pf.xy);
  vec2 n_x = mix(vec2(n00, n01), vec2(n10, n11), fade_xy.x);
  return 2.3 * mix(n_x.x, n_x.y, fade_xy.y);
}

const int OCTAVES = 4;
float fbm(vec2 p) {
  float value = 0.0;
  float amp = 1.0;
  for (int i = 0; i < OCTAVES; i++) {
    value += amp * abs(cnoise(p));
    p *= 3.0;      /* waveFrequency */
    amp *= 0.3;    /* waveAmplitude */
  }
  return value;
}

float pattern(vec2 p) {
  vec2 p2 = p - time * 0.0805;  /* waveSpeed — owner-tuned, do not change */
  return fbm(p + fbm(p2));
}

const float bayer[64] = float[64](
  0.0/64.0, 48.0/64.0, 12.0/64.0, 60.0/64.0,  3.0/64.0, 51.0/64.0, 15.0/64.0, 63.0/64.0,
  32.0/64.0,16.0/64.0, 44.0/64.0, 28.0/64.0, 35.0/64.0,19.0/64.0, 47.0/64.0, 31.0/64.0,
  8.0/64.0, 56.0/64.0,  4.0/64.0, 52.0/64.0, 11.0/64.0,59.0/64.0,  7.0/64.0, 55.0/64.0,
  40.0/64.0,24.0/64.0, 36.0/64.0, 20.0/64.0, 43.0/64.0,27.0/64.0, 39.0/64.0, 23.0/64.0,
  2.0/64.0, 50.0/64.0, 14.0/64.0, 62.0/64.0,  1.0/64.0,49.0/64.0, 13.0/64.0, 61.0/64.0,
  34.0/64.0,18.0/64.0, 46.0/64.0, 30.0/64.0, 33.0/64.0,17.0/64.0, 45.0/64.0, 29.0/64.0,
  10.0/64.0,58.0/64.0,  6.0/64.0, 54.0/64.0,  9.0/64.0,57.0/64.0,  5.0/64.0, 53.0/64.0,
  42.0/64.0,26.0/64.0, 38.0/64.0, 22.0/64.0, 41.0/64.0,25.0/64.0, 37.0/64.0, 21.0/64.0
);

void main() {
  vec2 block = floor(gl_FragCoord.xy / pixelSize);
  /* Wave field evaluated at the block corner — equivalent to the app's
     two-pass version sampling the wave buffer at the snapped UV. */
  vec2 uv = (block * pixelSize) / resolution - 0.5;
  uv.x *= resolution.x / resolution.y;
  /* Bright grayscale field: mix(black, 0.85 grey, f). */
  float g = pattern(uv) * 0.85;
  int x = int(mod(block.x, 8.0));
  int y = int(mod(block.y, 8.0));
  float threshold = bayer[y * 8 + x] - 0.25;
  g += threshold * (1.0 / 3.0);  /* step = 1/(colorNum-1) */
  g = clamp(g - 0.2, 0.0, 1.0);  /* reactbits bias */
  float level = floor(g * 3.0 + 0.5);
  vec3 mapped = ramp0;
  if (level > 0.5) mapped = ramp1;
  if (level > 1.5) mapped = ramp2;
  if (level > 2.5) mapped = ramp3;
  fragColor = vec4(mapped, 1.0);
}
`;

  function hexToRgb(hex) {
    const h = hex.slice(1);
    return [0, 2, 4].map((i) => Number.parseInt(h.slice(i, i + 2), 16) / 255);
  }

  function init() {
    const host = document.getElementById("bg");
    if (!host) return;

    // Film grain tile (port of effects/grain.tsx) — topmost background layer.
    const grain = host.querySelector(".bg-grain");
    if (grain) {
      const tile = document.createElement("canvas");
      tile.width = tile.height = 128;
      const ctx = tile.getContext("2d");
      if (ctx) {
        const img = ctx.createImageData(128, 128);
        for (let i = 0; i < img.data.length; i += 4) {
          // Centered low-alpha noise, exactly like the app's grain.tsx —
          // full-range opaque noise reads as dirt, not film.
          const v = 128 + (Math.random() * 2 - 1) * 118;
          img.data[i] = v;
          img.data[i + 1] = v;
          img.data[i + 2] = v;
          img.data[i + 3] = 26;
        }
        ctx.putImageData(img, 0, 0);
        grain.style.backgroundImage = `url(${tile.toDataURL()})`;
        grain.style.opacity = String(GRAIN_OPACITY);
      }
    }

    const canvas = document.createElement("canvas");
    canvas.className = "bg-canvas";
    canvas.setAttribute("aria-hidden", "true");
    host.prepend(canvas);

    const fail = () => {
      canvas.remove();
      host.classList.add("bg-static"); // veil-only ground, like the app
    };

    const gl = canvas.getContext("webgl2", {
      alpha: false,
      antialias: false,
      depth: false,
      stencil: false,
      preserveDrawingBuffer: false,
      powerPreference: "low-power",
    });
    if (!gl) return fail();

    function compile(type, src) {
      const sh = gl.createShader(type);
      gl.shaderSource(sh, src);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
        return null;
      }
      return sh;
    }

    const vs = compile(gl.VERTEX_SHADER, VERT);
    const fs = compile(gl.FRAGMENT_SHADER, FRAG);
    if (!vs || !fs) return fail();
    const prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.bindAttribLocation(prog, 0, "position");
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return fail();
    gl.useProgram(prog);

    // One fullscreen triangle.
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

    const uResolution = gl.getUniformLocation(prog, "resolution");
    const uTime = gl.getUniformLocation(prog, "time");
    const uPixelSize = gl.getUniformLocation(prog, "pixelSize");
    RAMP.forEach((hex, i) => {
      gl.uniform3fv(gl.getUniformLocation(prog, `ramp${i}`), hexToRgb(hex));
    });

    const desktop = window.matchMedia("(min-width: 1024px)");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

    function resize() {
      // DPR fixed at 1 — dither chunks are a look, not an artifact.
      // Sized from the window, not the host: #bg is fixed inset-0 so they are
      // equal, but the host measures 0 while overview mode display:none's it,
      // which would lock the canvas at 1x1 on a mid-overview resize.
      const w = Math.max(1, window.innerWidth);
      const h = Math.max(1, window.innerHeight);
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
      gl.viewport(0, 0, w, h);
      gl.uniform2f(uResolution, w, h);
      gl.uniform1f(uPixelSize, desktop.matches ? 2 : 3);
    }

    const t0 = performance.now();
    let raf = 0;
    let lost = false;

    function draw(time) {
      gl.uniform1f(uTime, time);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }

    function frame() {
      raf = 0;
      if (lost || document.hidden) return;
      if (reduced.matches) {
        draw(STATIC_TIME); // one static frame, no loop
        return;
      }
      draw((performance.now() - t0) / 1000);
      raf = requestAnimationFrame(frame);
    }

    function start() {
      if (!raf) raf = requestAnimationFrame(frame);
    }

    canvas.addEventListener("webglcontextlost", (e) => {
      e.preventDefault();
      lost = true;
      fail();
    });
    document.addEventListener("visibilitychange", start);
    window.addEventListener("resize", () => {
      resize();
      start();
    });
    desktop.addEventListener("change", () => {
      resize();
      start();
    });
    reduced.addEventListener("change", start);

    resize();
    start();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
