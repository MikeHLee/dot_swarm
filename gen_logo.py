#!/usr/bin/env python3
"""
Generate animated GIF logos for dot_swarm.

Usage:
    python gen_logo.py                          # default hexagon-text background
    python gen_logo.py --bg path/to/image.png   # overlay swarm on any image

Outputs:
    logo.gif   – wide animated banner (640×240)
    icon.gif   – square animated icon (128×128)
"""

import argparse
import math
import random
import numpy as np
from PIL import Image, ImageDraw

# ── CLI ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--bg", default=None,
                    help="Path to a background image (overrides hex-text default)")
parser.add_argument("--frames",  type=int, default=60)
parser.add_argument("--fps",     type=int, default=20)
parser.add_argument("--boids",   type=int, default=90)
parser.add_argument("--width",   type=int, default=640)
parser.add_argument("--height",  type=int, default=240)
args = parser.parse_args()

W, H       = args.width, args.height
FPS        = args.fps
N_FRAMES   = args.frames
N_BOIDS    = args.boids
DOT_R      = 3.5

# ── 5×9 pixel-font bitmaps ────────────────────────────────────────────────────
FONT = {
    'D': [0b11110,0b10001,0b10001,0b10001,0b10001,0b10001,0b10001,0b10001,0b11110],
    'O': [0b01110,0b10001,0b10001,0b10001,0b10001,0b10001,0b10001,0b10001,0b01110],
    'T': [0b11111,0b00100,0b00100,0b00100,0b00100,0b00100,0b00100,0b00100,0b00100],
    'S': [0b01111,0b10000,0b10000,0b10000,0b01110,0b00001,0b00001,0b00001,0b11110],
    'W': [0b10001,0b10001,0b10001,0b10001,0b10101,0b10101,0b10101,0b01010,0b01010],
    'A': [0b00100,0b01010,0b01010,0b10001,0b10001,0b11111,0b10001,0b10001,0b10001],
    'R': [0b11110,0b10001,0b10001,0b10001,0b11110,0b10100,0b10010,0b10001,0b10001],
    'M': [0b10001,0b11011,0b11011,0b10101,0b10101,0b10001,0b10001,0b10001,0b10001],
    ' ': [0b00000]*9,
}
CHAR_COLS = 5
CHAR_ROWS = 9
CHAR_GAP  = 1
TEXT      = "DOT SWARM"

# ── Helpers ───────────────────────────────────────────────────────────────────
def hex_vertices(cx, cy, r):
    """Flat-top hexagon vertices."""
    return [(cx + r * math.cos(math.radians(60*i)),
             cy + r * math.sin(math.radians(60*i))) for i in range(6)]

def pixel_set(text):
    on = set()
    col = 0
    for ch in text:
        bmp = FONT.get(ch, FONT[' '])
        for ri, row in enumerate(bmp):
            for ci in range(CHAR_COLS):
                if row & (1 << (CHAR_COLS - 1 - ci)):
                    on.add((col + ci, ri))
        col += CHAR_COLS + CHAR_GAP
    return on, col

# ── Background ────────────────────────────────────────────────────────────────
def make_hex_background(w, h):
    HEX_R    = 11
    HEX_H    = HEX_R * math.sqrt(3)
    COL_STEP = HEX_R * 2 * 0.75
    ROW_STEP = HEX_H

    on_pixels, total_cols = pixel_set(TEXT)
    grid_w = total_cols * COL_STEP + HEX_R * 0.5
    grid_h = CHAR_ROWS  * ROW_STEP + HEX_H  * 0.5
    off_x  = (w - grid_w) / 2
    off_y  = (h - grid_h) / 2

    img  = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    for gc in range(total_cols):
        for gr in range(CHAR_ROWS):
            cx = off_x + gc * COL_STEP + HEX_R
            cy = off_y + gr * ROW_STEP + HEX_H / 2
            if gc % 2 == 1: cy += ROW_STEP / 2
            pts   = hex_vertices(cx, cy, HEX_R - 1)
            is_on = (gc, gr) in on_pixels
            fill  = (10, 10, 10) if is_on else (230, 230, 230)
            out   = (0, 0, 0)    if is_on else (200, 200, 200)
            draw.polygon(pts, fill=fill, outline=out)

    return img

def load_custom_background(path, w, h):
    img = Image.open(path).convert("RGB")
    img = img.resize((w, h), Image.LANCZOS)
    return img

# ── Boid simulation (main canvas) ─────────────────────────────────────────────
class Boid:
    MAX_SPEED     = 2.8
    MAX_FORCE     = 0.14
    SEP_RADIUS    = 38.0   # keep-apart zone
    ALI_RADIUS    = 75.0   # alignment awareness
    COH_RADIUS    = 95.0   # cohesion awareness
    # Force weights — all pass through steer() so each is capped at MAX_FORCE
    SEP_W         = 2.8    # avoidance: highest priority
    ALI_W         = 1.2    # alignment: flow together
    COH_W         = 0.5    # cohesion: weak, just maintains loose group
    ORBIT_W       = 0.45   # tangential circling around group centre
    WANDER_W      = 1.2    # exploration (fades as inverse of home ramp)
    HOME_W_MAX    = 5.0    # home force ceiling — must dominate by t=1
    WANDER_RADIUS = 20.0
    WANDER_DIST   = 28.0
    WANDER_JITTER = 0.4

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.pos = np.array([random.uniform(0, w), random.uniform(0, h)], dtype=float)
        a = random.uniform(0, 2*math.pi)
        self.vel = np.array([math.cos(a), math.sin(a)]) * random.uniform(1.0, self.MAX_SPEED)
        self.acc = np.zeros(2)
        self.origin     = None   # set by capture_origin() after warmup
        self.origin_vel = None
        self.wander_theta = random.uniform(0, 2*math.pi)

    def capture_origin(self):
        """Record current state as the loop origin (call after warmup)."""
        self.origin     = self.pos.copy()
        self.origin_vel = self.vel.copy()

    def _limit(self, v, mag):
        n = np.linalg.norm(v)
        return v / n * mag if n > mag else v

    def _torus_vec(self, target):
        """Shortest vector from self.pos to target on the torus."""
        dx = target[0] - self.pos[0]
        dy = target[1] - self.pos[1]
        if abs(dx) > self.w / 2: dx -= math.copysign(self.w, dx)
        if abs(dy) > self.h / 2: dy -= math.copysign(self.h, dy)
        return np.array([dx, dy])

    def flock(self, boids, return_progress=0.0):
        sep = np.zeros(2); sc = 0
        ali = np.zeros(2); ac = 0
        coh = np.zeros(2); cc = 0

        for o in boids:
            if o is self: continue
            dv = self._torus_vec(o.pos)
            d  = np.linalg.norm(dv)
            if 0 < d < self.SEP_RADIUS:
                sep += -dv / d; sc += 1        # push away
            if 0 < d < self.ALI_RADIUS:
                ali += o.vel;    ac += 1
            if 0 < d < self.COH_RADIUS:
                coh += dv;       cc += 1        # relative offset, not absolute pos

        def steer(desired):
            n = np.linalg.norm(desired)
            if n == 0: return np.zeros(2)
            return self._limit(desired / n * self.MAX_SPEED - self.vel, self.MAX_FORCE)

        # ── flocking forces (gradually yield to home) ──
        flock_scale = 1.0 - return_progress * 0.6   # 1.0 → 0.4 over animation

        f = np.zeros(2)

        if sc: f += steer(sep / sc) * self.SEP_W * flock_scale
        if ac:
            av = ali / ac
            n  = np.linalg.norm(av)
            f += steer(av / n * self.MAX_SPEED if n else np.zeros(2)) * self.ALI_W * flock_scale
        if cc:
            f += steer(coh / cc) * self.COH_W * flock_scale
            # Circling: tangent to the average offset direction
            avg_offset = coh / cc
            tang = np.array([-avg_offset[1], avg_offset[0]])
            f += steer(tang) * self.ORBIT_W * flock_scale

        # ── explore ↔ home tradeoff (same smoothstep, complementary weights) ──
        # smooth_t: 0 at start → 1 at end (home wins)
        # explore_t: 1 at start → 0 at end (exploration wins early)
        t = return_progress
        smooth_t  = t * t * (3.0 - 2.0 * t)   # smoothstep
        explore_t = 1.0 - smooth_t             # exact complement

        # Wander (Reynolds steering toward a jittering point ahead)
        if explore_t > 0:
            self.wander_theta += random.uniform(-self.WANDER_JITTER, self.WANDER_JITTER)
            vn = np.linalg.norm(self.vel)
            if vn > 0:
                ahead  = self.pos + (self.vel / vn) * self.WANDER_DIST
                target = ahead + np.array([math.cos(self.wander_theta), math.sin(self.wander_theta)]) * self.WANDER_RADIUS
                f += steer(self._torus_vec(target)) * self.WANDER_W * explore_t

        # Home force: grows as explore decays — same smoothstep, complementary
        if self.origin is not None:
            home_vec = self._torus_vec(self.origin)
            f += steer(home_vec) * self.HOME_W_MAX * smooth_t

            # velocity matching in the second half
            if return_progress > 0.5:
                vel_blend = (return_progress - 0.5) / 0.5
                f += (self.origin_vel - self.vel) * 0.3 * vel_blend

        self.acc = f

    def update(self):
        self.vel  = self._limit(self.vel + self.acc, self.MAX_SPEED)
        self.vel *= 0.98                                    # gentle damping
        self.pos  = (self.pos + self.vel) % np.array([self.w, self.h])
        self.acc *= 0

# ── Icon boid (orbital vortex) ────────────────────────────────────────────────
class IconBoid:
    MAX_SPEED  = 2.2
    MAX_FORCE  = 0.14
    SEP_RADIUS = 14.0
    ALI_RADIUS = 30.0
    COH_RADIUS = 34.0

    def __init__(self, w, h):
        self.w, self.h = w, h
        angle = random.uniform(0, 2*math.pi)
        r     = random.uniform(10, 50)
        cx, cy = w/2, h/2
        self.pos = np.array([cx + math.cos(angle)*r, cy + math.sin(angle)*r], dtype=float)
        tang = np.array([-math.sin(angle), math.cos(angle)], dtype=float)
        self.vel = tang * random.uniform(0.8, self.MAX_SPEED)
        self.acc = np.zeros(2)

    def _limit(self, v, mag):
        n = np.linalg.norm(v)
        return v/n*mag if n > mag else v

    def flock_and_orbit(self, boids):
        sep = np.zeros(2); sc = 0
        ali = np.zeros(2); ac = 0
        coh = np.zeros(2); cc = 0
        cx, cy = self.w/2, self.h/2
        for o in boids:
            if o is self: continue
            d = np.linalg.norm(o.pos - self.pos)
            if 0 < d < self.SEP_RADIUS: sep += (self.pos-o.pos)/d; sc+=1
            if 0 < d < self.ALI_RADIUS: ali += o.vel;              ac+=1
            if 0 < d < self.COH_RADIUS: coh += o.pos;              cc+=1

        def steer(desired):
            n = np.linalg.norm(desired)
            if n == 0: return np.zeros(2)
            return self._limit(desired/n*self.MAX_SPEED - self.vel, self.MAX_FORCE)

        f = np.zeros(2)
        if sc: f += steer(sep/sc) * 2.0
        if ac: av=ali/ac; n=np.linalg.norm(av); f += steer(av/n*self.MAX_SPEED if n else av)
        if cc: f += steer(coh/cc - self.pos)

        to_c = np.array([cx, cy]) - self.pos
        dist = np.linalg.norm(to_c)
        if dist > 0:
            rhat = to_c / dist
            tang = np.array([-rhat[1], rhat[0]])   # CCW tangent
            f += tang * 0.12
            f += rhat * 0.06 * (dist - 42.0) / 42.0   # spring to ring r=42

        self.acc = f

    def update(self):
        self.vel = self._limit(self.vel + self.acc, self.MAX_SPEED)
        self.pos += self.vel
        margin = 8
        for i in range(2):
            sz = [self.w, self.h][i]
            if self.pos[i] < margin:   self.vel[i] += 0.3
            elif self.pos[i] > sz-margin: self.vel[i] -= 0.3
        self.acc *= 0

# ── Draw helpers ──────────────────────────────────────────────────────────────
def draw_boid(draw, pos, vel, r=DOT_R, color=(0,0,0)):
    x, y = pos
    draw.ellipse([x-r, y-r, x+r, y+r], fill=color)

def supersampled_icon_frame(boids_list, size=128, scale=4):
    IS = size * scale
    img  = Image.new("RGBA", (IS, IS), (255,255,255,255))
    draw = ImageDraw.Draw(img)

    # hex tile background
    hr = 12 * scale
    hh = hr * math.sqrt(3)
    cs = hr * 2 * 0.75
    rs = hh
    for ix in range(-1, int(IS/cs)+2):
        for iy in range(-1, int(IS/rs)+2):
            hcx = ix*cs + hr
            hcy = iy*rs + hh/2
            if ix%2 == 1: hcy += rs/2
            pts = hex_vertices(hcx, hcy, hr - scale)
            draw.polygon(pts, fill=(238,238,238), outline=(205,205,205))

    for b in boids_list:
        x, y = b.pos[0]*scale, b.pos[1]*scale
        r = 3*scale
        draw.ellipse([x-r, y-r, x+r, y+r], fill=(0,0,0,255))
        angle = math.atan2(b.vel[1], b.vel[0])
        tx, ty = x - math.cos(angle)*r*1.8, y - math.sin(angle)*r*1.8
        tr = r*0.45
        draw.ellipse([tx-tr, ty-tr, tx+tr, ty+tr], fill=(50,50,50,255))

    # circular mask
    mask = Image.new("L", (IS, IS), 0)
    pad  = 6*scale
    ImageDraw.Draw(mask).ellipse([pad, pad, IS-pad, IS-pad], fill=255)
    img.putalpha(mask)

    # ring overlay
    ring = Image.new("RGBA", (IS, IS), (0,0,0,0))
    ImageDraw.Draw(ring).ellipse([pad-2, pad-2, IS-pad+2, IS-pad+2],
                                  outline=(0,0,0,255), width=scale*4)
    img = Image.alpha_composite(img, ring)

    return img.resize((size, size), Image.LANCZOS)

# ── Main ──────────────────────────────────────────────────────────────────────
random.seed(42);  np.random.seed(42)

# Background
if args.bg:
    print(f"Loading background: {args.bg}")
    bg = load_custom_background(args.bg, W, H)
else:
    print("Generating hex-text background…")
    bg = make_hex_background(W, H)

# Grid initialization: spread boids evenly across canvas with jitter
print("Initialising main boids (grid spread)…")
cols = math.ceil(math.sqrt(N_BOIDS * W / H))
rows = math.ceil(N_BOIDS / cols)
cell_w, cell_h = W / cols, H / rows
boids = []
for i in range(N_BOIDS):
    b = Boid(W, H)
    col, row = i % cols, i // cols
    b.pos = np.array([
        (col + 0.5) * cell_w + random.uniform(-cell_w * 0.3, cell_w * 0.3),
        (row + 0.5) * cell_h + random.uniform(-cell_h * 0.3, cell_h * 0.3),
    ], dtype=float)
    b.pos[0] = max(5, min(W - 5, b.pos[0]))
    b.pos[1] = max(5, min(H - 5, b.pos[1]))
    boids.append(b)

# Warmup with separation-only so boids settle into natural spread (no cohesion pulling together)
print("Warmup (separation only, 60 steps)…")
for _ in range(60):
    for b in boids:
        sep = np.zeros(2); sc = 0
        for o in boids:
            if o is b: continue
            dv = b._torus_vec(o.pos)
            d  = np.linalg.norm(dv)
            if 0 < d < b.SEP_RADIUS:
                sep += -dv / d; sc += 1
        if sc:
            n = np.linalg.norm(sep / sc)
            desired = sep / sc / n * b.MAX_SPEED if n > 0 else np.zeros(2)
            b.acc = b._limit(desired - b.vel, b.MAX_FORCE) * b.SEP_W
    for b in boids: b.update()

# Capture origin AFTER warmup — frame 0 will match this state exactly
for b in boids: b.capture_origin()
print("Captured origin positions for seamless loop.")

# Icon boids
print("Initialising icon boids…")
ICON_SIZE  = 128
ICON_BOIDS = 120
icon_boids = [IconBoid(ICON_SIZE, ICON_SIZE) for _ in range(ICON_BOIDS)]
for _ in range(100):
    for b in icon_boids: b.flock_and_orbit(icon_boids)
    for b in icon_boids: b.update()

print(f"Rendering {N_FRAMES} frames…")
main_frames = []
icon_frames = []

for f in range(N_FRAMES):
    # Render BEFORE stepping so frame 0 = exact origin state, frame N-1 ≈ origin
    frame = bg.copy()
    draw  = ImageDraw.Draw(frame)
    for b in boids:
        draw_boid(draw, b.pos, b.vel)
    main_frames.append(frame.convert("P", palette=Image.ADAPTIVE, colors=16))

    icon_frame = supersampled_icon_frame(icon_boids, ICON_SIZE)
    icon_frames.append(icon_frame.convert("P", palette=Image.ADAPTIVE, colors=16))

    if f % 10 == 0: print(f"  frame {f}/{N_FRAMES}")

    # Step physics AFTER rendering
    return_progress = (f + 1) / N_FRAMES
    for b in boids: b.flock(boids, return_progress=return_progress)
    for b in boids: b.update()

    for b in icon_boids: b.flock_and_orbit(icon_boids)
    for b in icon_boids: b.update()

print("Saving logo.gif…")
ms = int(1000 / FPS)
main_frames[0].save("logo.gif", save_all=True, append_images=main_frames[1:],
                    loop=0, duration=ms, optimize=False)

print("Saving icon.gif…")
icon_frames[0].save("icon.gif", save_all=True, append_images=icon_frames[1:],
                    loop=0, duration=ms, optimize=False)

print("Done!  →  logo.gif  icon.gif")
