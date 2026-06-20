import board
import digitalio
import analogio
import busio
import displayio
import terminalio
import i2cdisplaybus
from adafruit_display_text import label
import adafruit_displayio_ssd1306
import vectorio
import audiobusio 
import struct
import time
from adafruit_bus_device.i2c_device import I2CDevice

class Hardware:
    def __init__(self):
        # --- 0. AUDIO OUT ---
        self.audio_out = audiobusio.I2SOut(bit_clock=board.GP2, word_select=board.GP3, data=board.GP4)

        # --- 1. NOTE BUTTONS ---
        self.note_btns = []
        custom_pins = [board.GP9, board.GP6, board.GP10, board.GP7, board.GP11, board.GP8, board.GP12]
        for pin in custom_pins:
            btn = digitalio.DigitalInOut(pin)
            btn.direction = digitalio.Direction.INPUT
            btn.pull = digitalio.Pull.UP
            self.note_btns.append(btn)
            
        # --- 2. FUNCTION BUTTONS ---
        self.fn_btns = []
        for pin in [board.GP18, board.GP19, board.GP22]:
            btn = digitalio.DigitalInOut(pin)
            btn.direction = digitalio.Direction.INPUT
            btn.pull = digitalio.Pull.UP
            self.fn_btns.append(btn)
            
        # --- 3. JOYSTICK ---
        self.joy_x = analogio.AnalogIn(board.GP28)
        self.joy_y = analogio.AnalogIn(board.GP26)
        self.joy_sw = digitalio.DigitalInOut(board.GP13)
        self.joy_sw.direction = digitalio.Direction.INPUT
        self.joy_sw.pull = digitalio.Pull.UP
        
        # --- 4. INTERNAL BATTERY MONITOR ---
        try:
            self.vbat_adc = analogio.AnalogIn(board.VOLTAGE_MONITOR)
        except Exception:
            self.vbat_adc = None
        
        # --- 5. OLED & MPU-6500 (I2C BUS) ---
        displayio.release_displays()
        # Fast enough for OLED, stable enough for the sensor
        self.i2c = busio.I2C(scl=board.GP21, sda=board.GP20, frequency=400000)
        
        self.display_bus = i2cdisplaybus.I2CDisplayBus(self.i2c, device_address=0x3C)
        self.display = adafruit_displayio_ssd1306.SSD1306(self.display_bus, width=128, height=64)
        
        # BARE METAL MPU INIT VIA TRAFFIC CONTROLLER
        self.has_mpu = False
        self.last_mpu_read = 0.0
        self.cached_tilt = (0.0, 0.0, 0.0)
        try:
            self.mpu_device = I2CDevice(self.i2c, 0x68)
            with self.mpu_device as device:
                device.write(bytes([0x6B, 0x00])) # Wake up
            time.sleep(0.1) # Spin-up delay
            self.has_mpu = True
            print("MPU-6500 Booted via I2CDevice Traffic Controller!")
        except Exception as e:
            print("Raw MPU init failed:", e)

        # ==========================================
        # SCREEN 1: THE LIVE JAM UI
        # ==========================================
        self.splash = displayio.Group()
        
        # G-Clef Pixel Art
        self.clef_bmp = displayio.Bitmap(8, 16, 2)
        self.clef_pal = displayio.Palette(2)
        self.clef_pal.make_transparent(0)
        self.clef_pal[1] = 0xFFFFFF 
        
        clef_pixels = [
            "  ##    ", " #  #   ", " #  #   ", "  ##    ",
            "  #     ", " ####   ", "# #  #  ", "# #  #  ",
            "# # ##  ", " ### #  ", "  #  #  ", " ####   ",
            "# #     ", "# #     ", " ###    ", "        "
        ]
        for y, row in enumerate(clef_pixels):
            for x, char in enumerate(row):
                if char == '#': self.clef_bmp[x, y] = 1

        self.clef_sprite = displayio.TileGrid(self.clef_bmp, pixel_shader=self.clef_pal, x=0, y=0)
        self.splash.append(self.clef_sprite)
        
        # Anchored Text Labels
        self.lbl_tl = label.Label(terminalio.FONT, text="C+0", anchor_point=(0.0, 0.0), anchored_position=(10, 0))
        self.lbl_tc = label.Label(terminalio.FONT, text="T1", anchor_point=(0.5, 0.0), anchored_position=(64, 0))
        self.lbl_tr = label.Label(terminalio.FONT, text="~MAJ", anchor_point=(1.0, 0.0), anchored_position=(128, 0))
        self.lbl_chord = label.Label(terminalio.FONT, text="Ready", anchor_point=(0.5, 0.5), anchored_position=(64, 32))
        self.lbl_bl = label.Label(terminalio.FONT, text="M:ONESHOT", anchor_point=(0.0, 1.0), anchored_position=(0, 63))
        self.lbl_br = label.Label(terminalio.FONT, text="W:SAW", anchor_point=(1.0, 1.0), anchored_position=(128, 63))

        self.splash.append(self.lbl_tl)
        self.splash.append(self.lbl_tc)
        self.splash.append(self.lbl_tr)
        self.splash.append(self.lbl_chord)
        self.splash.append(self.lbl_bl)
        self.splash.append(self.lbl_br)
        
        # ==========================================
        # SCREEN 2: THE GROOVEBOX STEP SEQUENCER UI
        # ==========================================
        self.step_ui = displayio.Group()
        self.lbl_step_info = label.Label(terminalio.FONT, text="STEP   [CURSOR: 1]", x=0, y=4, scale=1)
        
        self.step_bitmap = displayio.Bitmap(16, 7, 2) 
        self.step_palette = displayio.Palette(2)
        self.step_palette[0] = 0x000000 
        self.step_palette[1] = 0xFFFFFF 
        self.step_grid = displayio.TileGrid(self.step_bitmap, pixel_shader=self.step_palette)
        self.step_group = displayio.Group(scale=8, x=0, y=8) 
        self.step_group.append(self.step_grid)
        
        self.cursor_bmp = displayio.Bitmap(8, 56, 2)
        self.cursor_pal = displayio.Palette(2)
        self.cursor_pal.make_transparent(0) 
        self.cursor_pal[1] = 0xFFFFFF       
        
        for x in range(8):
            self.cursor_bmp[x, 0] = 1; self.cursor_bmp[x, 55] = 1
        for y in range(56):
            self.cursor_bmp[0, y] = 1; self.cursor_bmp[7, y] = 1
            
        self.cursor_sprite = displayio.TileGrid(self.cursor_bmp, pixel_shader=self.cursor_pal, x=0, y=8)

        self.step_ui.append(self.lbl_step_info)
        self.step_ui.append(self.step_group)
        self.step_ui.append(self.cursor_sprite) 

        self.display.root_group = self.splash

    # ==========================================
    # I2C MPU READ FUNCTION
    # ==========================================
    def read_tilt(self):
        """Reads all 3 axes using thread-safe I2CDevice locks."""
        if not getattr(self, 'has_mpu', False): 
            return 0.0, 0.0, 0.0
            
        now = time.monotonic()
        
        # Limit reads to 30 FPS so the OLED doesn't lag
        if now - self.last_mpu_read < 0.033:
            return self.cached_tilt
            
        buf = bytearray(6)
        try:
            # The 'with' statement safely pauses the OLED and grabs the bus
            with self.mpu_device as device:
                device.write_then_readinto(bytes([0x3B]), buf)
            
            x_raw, y_raw, z_raw = struct.unpack(">hhh", buf)
            
            tilt_x = (x_raw / 16384.0) * 9.8
            tilt_y = (y_raw / 16384.0) * 9.8
            tilt_z = (z_raw / 16384.0) * 9.8
            
            self.cached_tilt = (tilt_x, tilt_y, tilt_z)
            self.last_mpu_read = now
            return self.cached_tilt
            
        except Exception as e:
            # Silently return cache on I2C collision
            return self.cached_tilt

    # ==========================================
    # INPUT READERS
    # ==========================================
    def read_buttons(self):
        pressed = []
        for i, btn in enumerate(self.note_btns):
            if not btn.value: pressed.append(i)
        return pressed
        
    def read_fn(self):
        return not self.fn_btns[0].value
        
    def read_joystick(self):
        x = (self.joy_x.value - 32768) / 32768
        y = (self.joy_y.value - 32768) / 32768
        x = -x
        y = -y
        return x, y
    
    def read_battery_pct(self):
        if not self.vbat_adc: return 100
        voltage = (self.vbat_adc.value * 3.3 / 65535) * 3.0
        pct = int(((voltage - 3.2) / (4.2 - 3.2)) * 100)
        return max(0, min(100, pct)) 
        
    # ==========================================
    # UI UPDATERS
    # ==========================================
    def update_screen(self, track_str, key_name, wave_name, chord_name, mode_name, scale_name=""):
        self.lbl_tc.text = track_str
        self.lbl_tl.text = f"{key_name}" 
        self.lbl_tr.text = f"~{scale_name}"
        self.lbl_chord.text = chord_name
        self.lbl_bl.text = f"M:{mode_name[:7]}" 
        self.lbl_br.text = f"W:{wave_name}"

    def update_menu_screen(self, title, page, item, instructions, batt_pct="--"):
        self.lbl_tl.text = title
        self.lbl_tc.text = f"BAT: {batt_pct}%" 
        self.lbl_tr.text = page
        self.lbl_chord.text = item
        self.lbl_bl.text = instructions
        self.lbl_br.text = "" 

    def show_screen(self, screen_id):
        if screen_id == "LIVE":
            self.display.root_group = self.splash
        elif screen_id == "STEP":
            self.display.root_group = self.step_ui
            
    def update_step_screen(self, cursor_pos, wave_name, joy_zone, track_num, mode_name, total_steps, follow_on, play_step=-1):
        current_bar = (cursor_pos // 16) + 1
        total_bars = total_steps // 16
        local_x = cursor_pos % 16 
        
        for x in range(8): self.cursor_bmp[x, 54] = 0 
        current_page_start = (cursor_pos // 16) * 16
        if play_step >= 0 and current_page_start <= play_step < current_page_start + 16:
            pass 

        self.cursor_sprite.x = local_x * 8
        
        joy_str = "-"
        if joy_zone == (0, -1): joy_str = "^"
        elif joy_zone == (0, 1): joy_str = "v"
        elif joy_zone == (-1, 0): joy_str = "<"
        elif joy_zone == (1, 0): joy_str = ">"

        f_icon = "F" if follow_on else "M" 
        p_pos = (play_step % 16) + 1 if play_step >= 0 else "--"
        short_mode = mode_name[:3]
        
        self.lbl_step_info.text = f"T{track_num+1}:{short_mode} B:{current_bar}/{total_bars} [{f_icon}] P:{p_pos} J:{joy_str}"
    
    def update_mixer_screen(self, volumes, mutes, cursor_pos):
        self.mixer_group = displayio.Group()
        self.mixer_group.append(label.Label(terminalio.FONT, text="MASTER MIXER", x=25, y=4))
        
        labels = ["T1", "T2", "T3", "T4", "LIVE"] 
        y_pos = 14
        bar_h = 36
        bar_w = 14
        x_gap = 24
        
        for i in range(5):
            x_pos = 4 + (i * x_gap)
            vol_val = volumes[i]
            cur_bar_h = max(1, int(vol_val * bar_h))
            
            lbl_text = " M " if (i < 4 and mutes[i]) else labels[i]
            lbl_x = x_pos if i < 4 else x_pos - 4
            lbl = label.Label(terminalio.FONT, text=lbl_text, x=lbl_x, y=y_pos + bar_h + 8)
            self.mixer_group.append(lbl)
            
            outline = vectorio.Rectangle(pixel_shader=self.step_palette, width=bar_w, height=bar_h+2, x=x_pos, y=y_pos, color_index=1)
            self.mixer_group.append(outline)
            
            black_inside = vectorio.Rectangle(pixel_shader=self.step_palette, width=bar_w-2, height=bar_h, x=x_pos+1, y=y_pos+1, color_index=0)
            self.mixer_group.append(black_inside)
            
            fill = vectorio.Rectangle(pixel_shader=self.step_palette, width=bar_w-2, height=cur_bar_h, x=x_pos+1, y=y_pos + bar_h - cur_bar_h + 1, color_index=1)
            self.mixer_group.append(fill)
            
        cx = 7 + (cursor_pos * x_gap)
        cursor_lbl = label.Label(terminalio.FONT, text="v", x=cx, y=y_pos - 6)
        self.mixer_group.append(cursor_lbl)

        self.display.root_group = self.mixer_group

# ==========================================
# HERO JAM ENGINE
# ==========================================
class HeroJamEngine:
    def __init__(self):
        self.group = displayio.Group()

        self.bg_bitmap = displayio.Bitmap(128, 64, 2)
        self.bg_palette = displayio.Palette(2)
        self.bg_palette[0] = 0x000000 
        self.bg_palette[1] = 0xFFFFFF 
        self.bg_grid = displayio.TileGrid(self.bg_bitmap, pixel_shader=self.bg_palette)
        self.group.append(self.bg_grid)
        self.combo_label = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=54, y=25)
        self.group.append(self.combo_label)

        self.lane_x = [4, 22, 40, 58, 76, 94, 112] 
        for x in self.lane_x:
            for dx in range(8):
                self.bg_bitmap[x+dx, 50] = 1 
                self.bg_bitmap[x+dx, 54] = 1 
            for dy in range(5):
                self.bg_bitmap[x, 50+dy] = 1 
                self.bg_bitmap[x+7, 50+dy] = 1 

        self.score_bitmap = displayio.Bitmap(128, 10, 2)
        self.score_grid = displayio.TileGrid(self.score_bitmap, pixel_shader=self.bg_palette, x=0, y=0)
        self.group.append(self.score_grid)
        self.reset_score()

        self.note_bitmap = displayio.Bitmap(6, 3, 2)
        self.note_palette = displayio.Palette(2)
        self.note_palette[0] = 0x000000 
        self.note_palette.make_transparent(0) 
        self.note_palette[1] = 0xFFFFFF 
        
        for x in range(6):
            for y in range(3): self.note_bitmap[x, y] = 1

        self.pool_size = 15
        self.active_notes = [] 

        for _ in range(self.pool_size):
            sprite = displayio.TileGrid(self.note_bitmap, pixel_shader=self.note_palette, x=-10, y=-10)
            self.group.append(sprite)
            self.active_notes.append({"grid": sprite, "active": False, "target_time": 0.0, "lane": 0, "idx": 0})
            
    def update_combo(self, streak, multiplier):
        if streak < 10:
            self.combo_label.text = "" 
        else:
            self.combo_label.text = f"{multiplier}X"
            
    def reset_score(self):
        for x in range(128):
            for y in range(10): 
                self.score_bitmap[x, y] = 0 
                
        for x in range(1, 127, 2):
            self.score_bitmap[x, 4] = 1 
            
        for x in range(128):
            self.score_bitmap[x, 0] = 1
            self.score_bitmap[x, 9] = 1
        for y in range(10):
            self.score_bitmap[0, y] = 1
            self.score_bitmap[127, y] = 1

    def draw_score(self, idx, total, is_hit):
        if total <= 0: return
        
        usable_width = 126
        block_width = max(1, int(usable_width / total))
        start_x = 1 + int((idx / total) * usable_width)
        
        for w in range(block_width):
            if start_x + w < 127:
                for y in range(1, 9): 
                    if is_hit:
                        self.score_bitmap[start_x + w, y] = 1 
                    else:
                        self.score_bitmap[start_x + w, y] = 0 

    def spawn_note(self, lane_idx, target_time, note_idx):
        for note in self.active_notes:
            if not note["active"]:
                note["active"] = True
                note["lane"] = lane_idx
                note["target_time"] = target_time
                note["idx"] = note_idx
                note["grid"].x = self.lane_x[lane_idx] + 1 
                note["grid"].y = 10 
                return True
        return False 

    def update(self, current_time, fall_duration=2.0):
        speed_pixels_per_sec = 40.0 / fall_duration 
        missed_indices = []
        
        for note in self.active_notes:
            if note["active"]:
                time_left = note["target_time"] - current_time
                current_y = int(50 - (time_left * speed_pixels_per_sec))

                if current_y > 64:
                    note["active"] = False
                    note["grid"].y = -10 
                    missed_indices.append(note["idx"]) 
                else:
                    note["grid"].y = current_y
                    
        return missed_indices 

    def hide_note(self, note_dict):
        note_dict["active"] = False
        note_dict["grid"].y = -10