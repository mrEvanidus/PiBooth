#!/usr/bin/env python3
"""
======================================================
  Raspberry Pi Touchscreen Photo Booth
======================================================
  Requirements:
    sudo apt install python3-pygame python3-picamera2
    pip3 install pillow  (or: sudo apt install python3-pil)

  Run:
    python3 photobooth.py

  Customisation tips are marked with  >>>  throughout.
======================================================
"""

import pygame
import sys
import os
import time
import io
import threading
from datetime import datetime

# Pillow is used to composite the photo strip
from PIL import Image, ImageDraw, ImageFilter

# picamera2 for Raspberry Pi camera access
from picamera2 import Picamera2

# ─────────────────────────────────────────────
#  >>> GLOBAL CONFIGURATION  (easy to tweak)
# ─────────────────────────────────────────────

# Display resolution – set to your touchscreen's native resolution.
# The app forces landscape (width > height).
SCREEN_W, SCREEN_H = 800, 480

# How many seconds to count down before taking photos
COUNTDOWN_FROM = 5          # >>> change to 3 or 10 as preferred

# How many photos to take per session
NUM_PHOTOS = 3              # >>> change to 4 for a classic 4-photo strip

# Delay (seconds) between each photo capture
INTER_PHOTO_DELAY = 3       # >>> adjust spacing between shots

# Camera capture resolution (higher = slower, but sharper strip)
CAPTURE_W, CAPTURE_H = 1280, 960   # >>> e.g. (1920, 1440) for full quality

# Preview resolution (lower = smoother live feed)
PREVIEW_W, PREVIEW_H = 800, 480

# Output directory for saved strip images
OUTPUT_DIR = os.path.expanduser("~/photobooth_output")

# Strip thumbnail size – each photo inside the strip
THUMB_W, THUMB_H = 320, 240   # >>> wider strip: increase THUMB_W

# ─────────────────────────────────────────────
#  COLOUR PALETTE
# ─────────────────────────────────────────────
BLACK      = (0,   0,   0)
WHITE      = (255, 255, 255)
GREEN      = (50,  200, 80)
GREEN_DARK = (30,  140, 55)
FLASH_COL  = (255, 255, 255)
OVERLAY_BG = (0,   0,   0,  180)   # semi-transparent black (RGBA)

# Countdown number colour
COUNTDOWN_COL = (255, 220, 50)

# ─────────────────────────────────────────────
#  BORDER DEFINITIONS
#  Each entry: (display_name, bg_colour, inner_colour, accent_colour)
#  You can add as many as you like.
# ─────────────────────────────────────────────
BORDERS = [
    {
        "name":    "Classic Black",
        "bg":      (20,  20,  20),
        "inner":   (40,  40,  40),
        "accent":  (200, 200, 200),
        "text":    WHITE,
    },
    {
        "name":    "Rose Gold",
        "bg":      (180, 110, 100),
        "inner":   (220, 160, 140),
        "accent":  (255, 215, 170),
        "text":    WHITE,
    },
    {
        "name":    "Midnight Blue",
        "bg":      (10,  20,  60),
        "inner":   (20,  45, 100),
        "accent":  (80, 140, 255),
        "text":    (200, 220, 255),
    },
    {
        "name":    "Forest",
        "bg":      (20,  55,  20),
        "inner":   (35,  80,  35),
        "accent":  (100, 200, 100),
        "text":    (220, 255, 220),
    },
    {
        "name":    "Retro Cream",
        "bg":      (240, 230, 200),
        "inner":   (255, 248, 220),
        "accent":  (180, 120,  60),
        "text":    (80,  50,  20),
    },
    {
        "name":    "Neon Night",
        "bg":      (10,   5,  30),
        "inner":   (20,  10,  50),
        "accent":  (255,  50, 200),
        "text":    (255, 180, 255),
    },
]


# ═══════════════════════════════════════════════════════════
#  HELPER: draw a rounded rectangle (pygame doesn't have one)
# ═══════════════════════════════════════════════════════════
def draw_rounded_rect(surface, colour, rect, radius=20):
    pygame.draw.rect(surface, colour, rect, border_radius=radius)


# ═══════════════════════════════════════════════════════════
#  HELPER: render centred text
# ═══════════════════════════════════════════════════════════
def draw_text_centred(surface, text, font, colour, cx, cy):
    rendered = font.render(text, True, colour)
    r = rendered.get_rect(center=(cx, cy))
    surface.blit(rendered, r)


# ═══════════════════════════════════════════════════════════
#  BUILD PHOTO STRIP  (Pillow)
# ═══════════════════════════════════════════════════════════
def build_strip(photos_pil, border):
    """
    Composites NUM_PHOTOS thumbnails into a vertical strip with a
    decorative border using the selected border theme.

    Returns a pygame.Surface ready to blit.
    """
    pad        = 24          # >>> outer padding around strip
    gap        = 14          # >>> gap between photos
    corner_r   = 18          # >>> photo corner radius
    strip_pad  = 16          # >>> padding inside outer border

    tw, th = THUMB_W, THUMB_H
    strip_w = tw + strip_pad * 2
    strip_h = th * NUM_PHOTOS + gap * (NUM_PHOTOS - 1) + strip_pad * 2

    outer_w = strip_w + pad * 2
    outer_h = strip_h + pad * 2 + 50   # +50 for title text at bottom

    # ── outer backing card ──────────────────────────────────
    card = Image.new("RGB", (outer_w, outer_h), border["bg"])
    draw = ImageDraw.Draw(card)

    # decorative corner ticks
    tk = 18   # tick length
    ac = border["accent"]
    for (x1, y1, x2, y2) in [
        (0, 0,   tk,  0),    (0, 0,  0,  tk),
        (outer_w-tk, 0, outer_w-1, 0), (outer_w-1, 0, outer_w-1, tk),
        (0, outer_h-1, tk, outer_h-1), (0, outer_h-tk, 0, outer_h-1),
        (outer_w-tk, outer_h-1, outer_w-1, outer_h-1),
        (outer_w-1, outer_h-tk, outer_w-1, outer_h-1),
    ]:
        draw.line([(x1, y1), (x2, y2)], fill=ac, width=3)

    # ── inner strip panel ───────────────────────────────────
    inner_box = Image.new("RGB", (strip_w, strip_h), border["inner"])
    card.paste(inner_box, (pad, pad))

    # ── paste each thumbnail ────────────────────────────────
    for i, img in enumerate(photos_pil):
        thumb = img.resize((tw, th), Image.LANCZOS)

        # rounded mask
        mask = Image.new("L", (tw, th), 0)
        md   = ImageDraw.Draw(mask)
        md.rounded_rectangle([0, 0, tw-1, th-1], radius=corner_r, fill=255)

        y_off = pad + strip_pad + i * (th + gap)
        x_off = pad + strip_pad
        card.paste(thumb, (x_off, y_off), mask)

        # thin accent line below each photo (except last)
        if i < NUM_PHOTOS - 1:
            line_y = y_off + th + gap // 2
            draw.line([(x_off + 10, line_y), (x_off + tw - 10, line_y)],
                      fill=ac, width=1)

    # ── date stamp at bottom ────────────────────────────────
    date_str = datetime.now().strftime("%d %b %Y  |  %H:%M")
    # Pillow default font is tiny – that's fine for a small stamp
    draw.text((outer_w // 2, outer_h - 22), date_str,
              fill=border["accent"], anchor="mm")

    # ── convert Pillow → pygame Surface ─────────────────────
    mode   = card.mode
    size   = card.size
    raw    = card.tobytes()
    pg_sur = pygame.image.fromstring(raw, size, mode)
    return pg_sur


# ═══════════════════════════════════════════════════════════
#  MAIN APPLICATION CLASS
# ═══════════════════════════════════════════════════════════
class PhotoBooth:
    # ── states ───────────────────────────────────────────────
    STATE_HOME      = "home"
    STATE_COUNTDOWN = "countdown"
    STATE_CAPTURE   = "capture"
    STATE_STRIP     = "strip"

    def __init__(self):
        pygame.init()

        # Full-screen on the Pi touchscreen; use RESIZABLE for desktop testing
        flags = pygame.FULLSCREEN | pygame.NOFRAME
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)
        pygame.display.set_caption("Photo Booth")
        pygame.mouse.set_visible(False)   # hide mouse on touchscreen

        self.clock = pygame.time.Clock()
        self.state = self.STATE_HOME

        # ── fonts ──────────────────────────────────────────
        # >>> swap font paths for your own TTF fonts if desired
        self.font_huge    = pygame.font.SysFont("dejavusans", 160, bold=True)
        self.font_large   = pygame.font.SysFont("dejavusans",  52, bold=True)
        self.font_medium  = pygame.font.SysFont("dejavusans",  32)
        self.font_small   = pygame.font.SysFont("dejavusans",  22)
        self.font_btn     = pygame.font.SysFont("dejavusans",  30, bold=True)

        # ── camera ─────────────────────────────────────────
        self.cam = Picamera2()
        # Preview config: YUV420 for fast display
        preview_cfg = self.cam.create_preview_configuration(
            main={"size": (PREVIEW_W, PREVIEW_H), "format": "RGB888"}
        )
        self.cam.configure(preview_cfg)
        self.cam.start()
        time.sleep(1)   # let camera settle

        # ── state variables ────────────────────────────────
        self.countdown_val   = COUNTDOWN_FROM
        self.countdown_start = 0
        self.photos_pil      = []          # captured PIL Images
        self.photos_surf     = []          # pygame Surfaces (previews)
        self.current_border  = 0           # index into BORDERS list
        self.strip_surface   = None        # rendered strip Surface
        self.flash_alpha     = 0           # shutter flash opacity
        self.preview_frame   = None        # latest camera frame (Surface)
        self.capturing       = False       # thread guard

        # ── output directory ───────────────────────────────
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ─────────────────────────────────────────────────────────
    #  CAMERA HELPERS
    # ─────────────────────────────────────────────────────────
    def grab_preview_frame(self):
        """Capture a single RGB frame and return as pygame Surface."""
        arr = self.cam.capture_array("main")
        # arr shape: (H, W, 3)
        surf = pygame.surfarray.make_surface(arr.swapaxes(0, 1))
        return pygame.transform.scale(surf, (SCREEN_W, SCREEN_H))

    def take_photo(self):
        """
        Switch camera to still config, capture a hi-res PIL Image,
        then switch back to preview config.
        """
        self.cam.stop()
        still_cfg = self.cam.create_still_configuration(
            main={"size": (CAPTURE_W, CAPTURE_H), "format": "RGB888"}
        )
        self.cam.configure(still_cfg)
        self.cam.start()
        time.sleep(0.3)  # brief settle

        arr = self.cam.capture_array("main")
        img = Image.fromarray(arr)

        # Back to preview
        self.cam.stop()
        preview_cfg = self.cam.create_preview_configuration(
            main={"size": (PREVIEW_W, PREVIEW_H), "format": "RGB888"}
        )
        self.cam.configure(preview_cfg)
        self.cam.start()
        time.sleep(0.3)
        return img

    # ─────────────────────────────────────────────────────────
    #  CAPTURE SEQUENCE  (runs in a background thread)
    # ─────────────────────────────────────────────────────────
    def capture_sequence(self):
        """Takes NUM_PHOTOS with INTER_PHOTO_DELAY seconds between each."""
        self.photos_pil = []
        for i in range(NUM_PHOTOS):
            # Trigger flash effect on main thread via flag
            self.flash_alpha = 255
            img = self.take_photo()
            self.photos_pil.append(img)

            # Save full-res image to disk
            fname = datetime.now().strftime("photo_%Y%m%d_%H%M%S") + f"_{i+1}.jpg"
            img.save(os.path.join(OUTPUT_DIR, fname))

            if i < NUM_PHOTOS - 1:
                time.sleep(INTER_PHOTO_DELAY)

        # Build the strip and switch state
        self.strip_surface = build_strip(self.photos_pil, BORDERS[self.current_border])
        self.state = self.STATE_STRIP
        self.capturing = False

    # ─────────────────────────────────────────────────────────
    #  BUTTON FACTORY
    # ─────────────────────────────────────────────────────────
    def _btn_rect(self, cx, cy, w, h):
        return pygame.Rect(cx - w // 2, cy - h // 2, w, h)

    def draw_button(self, text, cx, cy, w=200, h=60,
                    bg=GREEN, hover_bg=GREEN_DARK, text_col=WHITE,
                    active=False, radius=16):
        rect = self._btn_rect(cx, cy, w, h)
        colour = hover_bg if active else bg
        draw_rounded_rect(self.screen, colour, rect, radius)
        # subtle inner highlight
        highlight = pygame.Rect(rect.x + 4, rect.y + 4, rect.w - 8, rect.h // 2 - 4)
        s = pygame.Surface((highlight.w, highlight.h), pygame.SRCALPHA)
        s.fill((255, 255, 255, 30))
        self.screen.blit(s, highlight.topleft)
        draw_text_centred(self.screen, text, self.font_btn, text_col, cx, cy)
        return rect

    # ─────────────────────────────────────────────────────────
    #  SCREENS
    # ─────────────────────────────────────────────────────────
    def draw_home(self):
        # Background gradient (simple two-tone)
        self.screen.fill((15, 15, 25))
        # Decorative circle accents
        pygame.draw.circle(self.screen, (30, 30, 60), (SCREEN_W - 80, 80), 120)
        pygame.draw.circle(self.screen, (30, 30, 60), (80, SCREEN_H - 80), 90)

        draw_text_centred(self.screen, "PHOTO BOOTH",
                          self.font_large, WHITE, SCREEN_W // 2, SCREEN_H // 2 - 60)
        draw_text_centred(self.screen, "Touch START to begin",
                          self.font_small, (160, 160, 180),
                          SCREEN_W // 2, SCREEN_H // 2 - 10)

        start_rect = self.draw_button(
            "Start!", SCREEN_W // 2, SCREEN_H // 2 + 70,
            w=220, h=70, bg=GREEN, hover_bg=GREEN_DARK
        )
        return {"start": start_rect}

    def draw_countdown(self):
        # Live camera preview as background
        frame = self.grab_preview_frame()
        self.screen.blit(frame, (0, 0))

        # Darkening overlay
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120))
        self.screen.blit(overlay, (0, 0))

        # Countdown number
        elapsed = time.time() - self.countdown_start
        remaining = max(0, COUNTDOWN_FROM - int(elapsed))

        if remaining > 0:
            draw_text_centred(self.screen, str(remaining),
                              self.font_huge, COUNTDOWN_COL,
                              SCREEN_W // 2, SCREEN_H // 2)
            draw_text_centred(self.screen, "Get ready…",
                              self.font_medium, WHITE,
                              SCREEN_W // 2, SCREEN_H // 2 + 110)
        else:
            # Time's up – switch to capture
            draw_text_centred(self.screen, "Smile!",
                              self.font_large, COUNTDOWN_COL,
                              SCREEN_W // 2, SCREEN_H // 2)
            self.state = self.STATE_CAPTURE
            if not self.capturing:
                self.capturing = True
                t = threading.Thread(target=self.capture_sequence, daemon=True)
                t.start()

    def draw_capture(self):
        # Live preview while capture thread works
        frame = self.grab_preview_frame()
        self.screen.blit(frame, (0, 0))

        # Flash effect
        if self.flash_alpha > 0:
            flash_surf = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            flash_surf.fill((255, 255, 255, self.flash_alpha))
            self.screen.blit(flash_surf, (0, 0))
            self.flash_alpha = max(0, self.flash_alpha - 25)

        # Photo counter
        taken = len(self.photos_pil)
        draw_text_centred(self.screen,
                          f"Photo {taken + 1} of {NUM_PHOTOS}",
                          self.font_medium, WHITE,
                          SCREEN_W // 2, 40)

    def draw_strip(self):
        border = BORDERS[self.current_border]
        self.screen.fill(border["bg"])

        # ── strip panel (centred left side) ──────────────────
        strip_area_w = SCREEN_W // 2
        if self.strip_surface:
            sw, sh = self.strip_surface.get_size()
            # Scale strip to fit left half
            scale = min((strip_area_w - 40) / sw, (SCREEN_H - 40) / sh)
            new_w = int(sw * scale)
            new_h = int(sh * scale)
            scaled = pygame.transform.smoothscale(self.strip_surface, (new_w, new_h))
            sx = (strip_area_w - new_w) // 2
            sy = (SCREEN_H - new_h) // 2
            self.screen.blit(scaled, (sx, sy))

        # ── right side: title + border buttons ──────────────
        rx = strip_area_w + 20
        draw_text_centred(self.screen, "Your Photos!",
                          self.font_medium, border["text"],
                          strip_area_w + (SCREEN_W - strip_area_w) // 2, 40)
        draw_text_centred(self.screen, "Choose a border:",
                          self.font_small, border["text"],
                          strip_area_w + (SCREEN_W - strip_area_w) // 2, 75)

        btn_cx = strip_area_w + (SCREEN_W - strip_area_w) // 2
        btn_rects = {}
        
        
        # # Arrange border buttons in a 2-column mini grid
        # cols = 2
        # bw, bh = 155, 44
        # hgap, vgap = 10, 8
        # total_cols_w = cols * bw + (cols - 1) * hgap
        # start_x = btn_cx - total_cols_w // 2

        # for idx, b in enumerate(BORDERS):
        #     col = idx % cols
        #     row = idx // cols
        #     bx = start_x + col * (bw + hgap) + bw // 2
        #     by = 115 + row * (bh + vgap) + bh // 2
        #     active = (idx == self.current_border)
        #     bg_col  = b["accent"] if active else b["inner"]
        #     txt_col = b["bg"]     if active else b["text"]
        #     r = self.draw_button(b["name"], bx, by, w=bw, h=bh,
        #                          bg=b["inner"], hover_bg=b["accent"],
        #                          text_col=txt_col, active=active, radius=10)
        #     btn_rects[f"border_{idx}"] = r

        # ── Border cycle buttons ──────────────────────────────────
        border_name = BORDERS[self.current_border]["name"]
        draw_text_centred(self.screen, border_name,
                        self.font_small, border["text"],
                        btn_cx, 130)

        prev_rect = self.draw_button("< Prev", btn_cx - 95, 180,
                                    w=150, h=50, bg=border["inner"],
                                    text_col=border["text"], radius=10)
        next_rect = self.draw_button("Next >", btn_cx + 95, 180,
                                    w=150, h=50, bg=border["inner"],
                                    text_col=border["text"], radius=10)
        btn_rects["prev_border"] = prev_rect
        btn_rects["next_border"] = next_rect

        # ── Save & Retake buttons ─────────────────────────────
        bottom_y = SCREEN_H - 55
        save_rect  = self.draw_button("Save",   btn_cx - 95, bottom_y,
                                      w=160, h=50, bg=(60, 100, 180))
        again_rect = self.draw_button("Retake", btn_cx + 95, bottom_y,
                                      w=160, h=50, bg=(180, 60, 60))
        btn_rects["save"]   = save_rect
        btn_rects["retake"] = again_rect
        return btn_rects

    # ─────────────────────────────────────────────────────────
    #  MAIN LOOP
    # ─────────────────────────────────────────────────────────
    def run(self):
        btn_rects = {}

        while True:
            # ── Events ───────────────────────────────────────
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.shutdown()
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.shutdown()

                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                    # Normalise touch and mouse to a single point
                    if event.type == pygame.FINGERDOWN:
                        pos = (int(event.x * SCREEN_W), int(event.y * SCREEN_H))
                    else:
                        pos = event.pos

                    if self.state == self.STATE_HOME:
                        if btn_rects.get("start") and \
                                btn_rects["start"].collidepoint(pos):
                            self.state = self.STATE_COUNTDOWN
                            self.countdown_start = time.time()

                    elif self.state == self.STATE_STRIP:
                        for key, rect in btn_rects.items():
                            if rect.collidepoint(pos):
                                # if key.startswith("border_"):
                                #     idx = int(key.split("_")[1])
                                #     self.current_border = idx
                                #     # Rebuild strip with new border
                                #     self.strip_surface = build_strip(
                                #         self.photos_pil, BORDERS[idx]
                                #     )
                                if key == "retake":
                                    self.state = self.STATE_CAPTURE
                                    self.photos_pil = []
                                elif key == "save":
                                    self.save_strip()
                                    time.sleep(3)
                                    self.state = self.STATE_HOME
                                elif key == "prev_border":
                                    self.current_border = (self.current_border - 1) % len(BORDERS)
                                    self.strip_surface = build_strip(self.photos_pil, BORDERS[self.current_border])
                                elif key == "next_border":
                                    self.current_border = (self.current_border + 1) % len(BORDERS)
                                    self.strip_surface = build_strip(self.photos_pil, BORDERS[self.current_border])


            # ── Draw current state ────────────────────────────
            btn_rects = {}

            if self.state == self.STATE_HOME:
                btn_rects = self.draw_home()
            elif self.state == self.STATE_COUNTDOWN:
                self.draw_countdown()
            elif self.state == self.STATE_CAPTURE:
                self.draw_capture()
            elif self.state == self.STATE_STRIP:
                btn_rects = self.draw_strip()

            pygame.display.flip()
            self.clock.tick(30)   # >>> 30 fps is fine; raise to 60 if display allows

    # ─────────────────────────────────────────────────────────
    #  SAVE STRIP TO DISK
    # ─────────────────────────────────────────────────────────
    def save_strip(self):
        if not self.photos_pil:
            print("[PhotoBooth] Save failed: no photos in memory")
            return

        try:
            border = BORDERS[self.current_border]
            fname = datetime.now().strftime("strip_%Y%m%d_%H%M%S") + ".jpg"
            path  = os.path.join(OUTPUT_DIR, fname)

            # Save via the already-rendered strip surface rather than re-building
            raw  = pygame.image.tostring(self.strip_surface, "RGB")
            w, h = self.strip_surface.get_size()
            pil  = Image.frombytes("RGB", (w, h), raw)
            pil.save(path, quality=92)
            print(f"[PhotoBooth] Strip saved → {path}")
            msg = f"Saved to {OUTPUT_DIR}"

        except Exception as e:
            print(f"[PhotoBooth] Save error: {e}")
            msg = "Save failed! Check terminal."

        # On-screen confirmation
        overlay = pygame.Surface((SCREEN_W, 60), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        self.screen.blit(overlay, (0, SCREEN_H // 2 - 30))
        draw_text_centred(self.screen, msg,
                        self.font_small, GREEN, SCREEN_W // 2, SCREEN_H // 2)
        pygame.display.flip()
        time.sleep(1.8)
        # if not self.photos_pil:
        #     return
        # border = BORDERS[self.current_border]
        # fname = datetime.now().strftime("strip_%Y%m%d_%H%M%S") + ".jpg"
        # path  = os.path.join(OUTPUT_DIR, fname)
        # # Re-render strip at full resolution (no scaling) and save
        # full_strip = build_strip(self.photos_pil, border)
        # # Convert pygame Surface → PIL → save
        # raw  = pygame.image.tostring(full_strip, "RGB")
        # w, h = full_strip.get_size()
        # pil  = Image.frombytes("RGB", (w, h), raw)
        # pil.save(path, quality=92)
        # print(f"[PhotoBooth] Strip saved → {path}")

        # # Brief on-screen confirmation
        # overlay = pygame.Surface((SCREEN_W, 60), pygame.SRCALPHA)
        # overlay.fill((0, 0, 0, 200))
        # self.screen.blit(overlay, (0, SCREEN_H // 2 - 30))
        # draw_text_centred(self.screen, f"Saved! → {fname}",
        #                   self.font_small, GREEN, SCREEN_W // 2, SCREEN_H // 2)
        # pygame.display.flip()
        # time.sleep(1.8)

    # ─────────────────────────────────────────────────────────
    #  CLEANUP
    # ─────────────────────────────────────────────────────────
    def shutdown(self):
        print("[PhotoBooth] Shutting down…")
        self.cam.stop()
        pygame.quit()
        sys.exit(0)


# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    booth = PhotoBooth()
    booth.run()