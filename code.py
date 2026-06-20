#code.py main firmware logic for Anka-Jam
import time
import json
import os
import gc 
import random 
import microcontroller
import usb_midi
import adafruit_midi
from adafruit_midi.note_on import NoteOn
from adafruit_midi.note_off import NoteOff
from adafruit_midi.control_change import ControlChange
from adafruit_midi.pitch_bend import PitchBend
import board
import digitalio
import usb_host
import adafruit_usb_host_midi
import usb.core
from lib.ankajam_hardware import Hardware
from lib.ankajam_theory import MusicTheory
from lib.ankajam_synth import SynthEngine
from lib.ankajam_hardware import HeroJamEngine

try:
    onboard_led = digitalio.DigitalInOut(board.LED)
    onboard_led.direction = digitalio.Direction.OUTPUT
except Exception:
    onboard_led = None

# ---> FIX 1: RESTORE YOUR EXACT HARDWARE PINS <---
try:
    usb_host.Port(board.GP16, board.GP17)
    print("USB Host port initialized.")
except Exception as e:
    print("USB Host failed:", e)

print("Booting Anka-Jam v1.5 [Mixer & Overdub Engine]...")
hw = Hardware()
theory = MusicTheory()
synth = SynthEngine(hw.audio_out)
hero_engine = HeroJamEngine()

try:
    midi = adafruit_midi.MIDI(midi_out=usb_midi.ports[1], out_channel=0)
except Exception:
    midi = None

# --- USB KEYBOARD GLOBALS ---
usb_midi_in = None
host_midi_device = None
usb_high_perf = False 
last_usb_read_time = 0

midi_active_timers = {} 
last_midi_read_time = 0 
usb_high_perf = False
last_pitch_val = 8192
last_usb_scan_time = 0

def check_usb_keyboard(now):
    global midi_in, last_usb_scan_time, midi_active_timers, last_midi_read_time, usb_high_perf, last_pitch_val
    
    # --- DYNAMIC CONNECTION CHECK ---
    if 'midi_in' not in globals() or not midi_in:
        if now - last_usb_scan_time > 1.0:
            for device in usb.core.find(find_all=True):
                try:
                    host_midi_device = adafruit_usb_host_midi.MIDI(device, timeout=0.01)
                    midi_in = adafruit_midi.MIDI(midi_in=host_midi_device, in_channel="ALL")
                    print(f"\n[USB] SUCCESS: EasyKey Connected! (VID: {hex(device.idVendor)})")
                    break 
                except Exception:
                    continue 
            last_usb_scan_time = now
        return 
        
    # ---> THE TIME-SLICING FIX <---
    if not usb_high_perf and (now - last_midi_read_time < 0.015):
        return
        
    last_midi_read_time = now 
    
    # --- MESSAGE READING ---
    try:
        msg = midi_in.receive()
        while msg is not None:
            
            # ==========================================
            # ---> DIAGNOSTIC PRINT: WHAT DID WE GET? <---
            # ==========================================
            print(f"\n[MIDI RCV] Type: {type(msg).__name__}")
            
            # A. Note On
            if isinstance(msg, NoteOn) and msg.velocity > 0:
                vel_float = (msg.velocity / 127.0) ** (1/2) 
                
                # ---> DIAGNOSTIC: Check the raw velocity number!
                print(f"   -> PRESS Note: {msg.note} | Raw Vel: {msg.velocity} | Calc Float: {vel_float:.2f}")
                
                execute_audio(f"EXT_{msg.note}", "PRESS", [msg.note], now, midi_vel=vel_float)
                midi_active_timers[msg.note] = now 
                
            # B. Note Off
            elif isinstance(msg, NoteOff) or (isinstance(msg, NoteOn) and msg.velocity == 0):
                print(f"   -> RELEASE Note: {msg.note}")
                synth.release_live(f"EXT_{msg.note}")
                midi_active_timers.pop(msg.note, None) 
                
            # C. Mod Wheel & Rotary Encoder
            elif isinstance(msg, ControlChange):
                
                # ---> DIAGNOSTIC: See exactly what the knobs/buttons send!
                print(f"   -> CC MESSAGE! Control Number: {msg.control} | Value: {msg.value}")
                
                # CC1: Emergency Exit from Headless Mode
                if msg.control == 1 and usb_high_perf:
                    usb_high_perf = False
                    hw.show_screen("LIVE")
                    hw.update_screen("USB", "EXIT", "MOD WHEEL", "KBOARD", "MODE", "ACTIVE")
                    print("   -> Exiting Headless Mode via CC1!")
                    
                # CC7: Rotary Encoder (Mixer Volume)
                elif msg.control == 7:
                    track_states[active_track]["volume"] = msg.value / 127.0
                    print(f"   -> Track {active_track} Volume updated to: {track_states[active_track]['volume']:.2f}")
                    if system_state == "MIXER":
                        hw.update_mixer_screen([t.get("volume", 0.8) for t in track_states] + [live_synth_vol], [t.get("muted", False) for t in track_states], mixer_cursor)
                        
            # D. Pitch Bend (Octave Buttons)
            elif isinstance(msg, PitchBend):
                print(f"   -> PITCH BEND! Value: {msg.pitch_bend}")
                
                if msg.pitch_bend > 12000 and last_pitch_val <= 12000:
                    track_states[active_track]["octave"] = min(1, track_states[active_track]["octave"] + 1)
                    theory.last_chord_notes = []; refresh_screen(now_time=now)
                    print(f"   -> Shifted Octave UP to: {track_states[active_track]['octave']}")
                elif msg.pitch_bend < 4000 and last_pitch_val >= 4000:
                    track_states[active_track]["octave"] = max(-2, track_states[active_track]["octave"] - 1)
                    theory.last_chord_notes = []; refresh_screen(now_time=now)
                    print(f"   -> Shifted Octave DOWN to: {track_states[active_track]['octave']}")
                last_pitch_val = msg.pitch_bend

            # Grab the next message in the hardware buffer
            msg = midi_in.receive() 

        # --- THE SAFETY NET ---
        for note, start_time in list(midi_active_timers.items()):
            if now - start_time > 5.0:
                synth.release_live(f"EXT_{note}")
                midi_active_timers.pop(note, None)

    except Exception as e:
        print(f"\n[USB] Keyboard Disconnected! ({e})")
        midi_in = None 
        midi_active_timers.clear()


active_midi_notes = {}

def trigger_midi(tag, notes, vel=100):
    if get_val("SYS", "MIDI OUT") == 1 and midi is not None:
        active_midi_notes[tag] = notes
        for n in notes:
            try: midi.send(NoteOn(int(n), vel))
            except: pass

def release_midi(tag):
    if get_val("SYS", "MIDI OUT") == 1 and midi is not None and tag in active_midi_notes:
        for n in active_midi_notes[tag]:
            try: midi.send(NoteOff(int(n), 0))
            except: pass
        del active_midi_notes[tag]

def release_all_midi():
    if midi is not None:
        for tag, notes in list(active_midi_notes.items()):
            for n in notes:
                try: midi.send(NoteOff(int(n), 0))
                except: pass
        active_midi_notes.clear()

class ButtonDebouncer:
    def __init__(self, pin):
        self.pin = pin
        self.current_state = not pin.value 
        self.last_state = self.current_state
        self.last_bounce_time = time.monotonic()
        self.just_pressed = False
        self.just_released = False

    def update(self):
        self.just_pressed = False
        self.just_released = False
        raw_state = not self.pin.value
        if raw_state != self.last_state: self.last_bounce_time = time.monotonic()
        threshold = 0.01 if raw_state else 0.02 
        if (time.monotonic() - self.last_bounce_time) > threshold: 
            if raw_state != self.current_state:
                self.current_state = raw_state
                if self.current_state: self.just_pressed = True
                else: self.just_released = True
        self.last_state = raw_state

fn1_btn = ButtonDebouncer(hw.fn_btns[0])
fn2_btn = ButtonDebouncer(hw.fn_btns[1])
fn3_btn = ButtonDebouncer(hw.fn_btns[2])
note_btn_debouncers = [ButtonDebouncer(btn) for btn in hw.note_btns]

# ---> MASTER STATES <---
system_state = "PLAY" # PLAY, MENU, MIXER
current_wave_name = "SAW"
modes = ["ONESHOT", "STRUM", "ARPEGGIO", "PSYCH", "DRUM", "DRONE", "REPEAT", "LEAD"]
current_mode_idx = 0
current_octave = 0 
in_step_mode = False 
active_track = 0 
step_cursor = 0
track_states = [{"len": 16, "mode": 0, "wave": 1, "octave": 0, "muted": False, "volume": 0.8} for _ in range(4)]
live_synth_vol = 1.0 
follow_mode = True 
mixer_cursor = 0
master_vol = 1.0

# Variables for Hero-Jam
hero_state = "SELECT" # SELECT, PLAY, END
hero_tab_idx = 1
hero_start_time = 0
hero_event_idx = 0
hero_hits = 0
hero_total = 0
hero_pause_start = 0 
hero_last_draw = 0 # Tracks the last frame drawn

# ---> LOOPER STATES <---
looper_state = "OFF" # OFF, WAITING, RECORD, PLAY, OVERDUB
loop_events = []
loop_start_time = 0
loop_length = 0
playback_start = 0
next_event_idx = 0
last_loop_pos = 0
looper_bars = 0 

last_repeat_time = 0 
ear_target = -1
ear_state = "WAIT" 
ear_timer = 0
joy_sw_press_time = 0; joy_sw_handled = False; joy_sw_last = True; quantize_enabled = False

tab_data = None
auto_chords = []
last_viewed_page = -1 
last_viewed_track = -1 
step_cursor = 0
last_page_seen = -1
last_buttons_state = set()

def get_joy_zone(x, y):
    xd = -1 if x < -0.6 else (1 if x > 0.6 else 0)
    yd = -1 if y < -0.6 else (1 if y > 0.6 else 0)
    return (xd, yd)
last_joy_zone = (0, 0)

joy_x_state, joy_y_state = 0, 0
joy_x_timer, joy_y_timer = 0, 0

tab_files = []
try:
    for f in os.listdir("/tabs"):
        if f.endswith(".json"): tab_files.append(f)
except Exception: pass
tab_list = ["OFF"] + [f.replace(".json", "")[:8] for f in tab_files] 

current_menu_level = "ROOT"
menu_idx = 0
menu_editing = False

menus = {
    "ROOT": ["ADSR >", "EFFECTS >", "JAM >", "SCALE >", "SYS >", "GAMES >"],
    "ADSR": [
        {"id": "PRESET", "type": "list", "val": 0, "list": ["KEYS", "PAD", "PLUCK", "SWELL", "MANUAL"]},
        {"id": "ATK",  "type": "num",  "val": 0.05, "min": 0.00, "max": 2.00, "step": 0.05},
        {"id": "DEC",  "type": "num",  "val": 0.10, "min": 0.00, "max": 2.00, "step": 0.05},
        {"id": "SUS",  "type": "num",  "val": 0.70, "min": 0.00, "max": 1.00, "step": 0.05},
        {"id": "REL",  "type": "num",  "val": 0.80, "min": 0.05, "max": 4.00, "step": 0.05},
        {"id": "BACK", "type": "back"}
    ],
    "EFFECTS": [
        {"id": "CHORUS","type": "list","val": 0, "list": ["OFF", "ON"]},
        {"id": "DELAY", "type": "list","val": 0, "list": ["OFF", "1/4", "1/8", "1/16"]},
        {"id": "GLIDE", "type": "num",  "val": 0.0, "min": 0.0, "max": 0.5, "step": 0.05},
        {"id": "LFO RATE","type": "num","val": 1.0,  "min": 0.1,  "max": 8.0,  "step": 0.5},
        {"id": "TREMOLO", "type": "list", "val": 0, "list": ["OFF", "ON"]}, 
        {"id": "V-LEAD","type": "list","val": 0, "list": ["OFF", "ON"]},
        {"id": "VEL MIN","type": "num", "val": 0.8, "min": 0.2, "max": 1.0, "step": 0.1},
        {"id": "KBD MIN","type": "num", "val": 0.5, "min": 0.0, "max": 1.0, "step": 0.1},
        {"id": "BACK", "type": "back"}
    ],
    "JAM": [
        {"id": "Q-GRID", "type": "list", "val": 4, "list": ["1/1", "1/2", "1/4", "1/8", "1/16"]},
        {"id": "TAB", "type": "list", "val": 0, "list": tab_list if len(tab_list) > 0 else ["OFF"]},
        {"id": "AUTO", "type": "list", "val": 0, "list": ["OFF", "POP", "DARK", "LOFI", "EPIC", "JAZZ"]},
        {"id": "BACK", "type": "back"}
    ],
    "SCALE": [
        {"id": "MODE", "type": "list", "val": 0, "list": ["MAJOR", "NAT MIN", "HARM MIN", "MEL MIN", "MAJ PENT", "MIN PENT", "BLUES", "DORIAN", "MIXOLYD", "LYDIAN"]},
        {"id": "BACK", "type": "back"}
    ],
    "SYS": [
        {"id": "MIDI OUT","type": "list","val": 0, "list": ["OFF", "ON"]},
        {"id": "CLICK","type": "list","val": 0, "list": ["OFF", "LED", "LED+CLK"]},
        {"id": "BACK", "type": "back"}
    ],
    "GAMES": [
        {"id": "EAR TRAIN", "type": "action", "val": "EARTRAINER"},
        {"id": "HERO-JAM", "type": "action", "val": "HEROJAM"},
        {"id": "BACK", "type": "back"}
    ]
}

def get_val(cat, item_id):
    for item in menus[cat]:
        if item.get("id") == item_id: return item["val"]
    return 0

def set_val(cat, item_id, val):
    for item in menus[cat]:
        if item.get("id") == item_id: item["val"] = val

def generate_progression(genre_idx):
    if genre_idx == 1:   return [(0,0,0), (random.choice([4,5]),0,0), (random.choice([3,5]),0,0), (random.choice([3,4]),0,0)]
    elif genre_idx == 2: return [(5,0,0), (3,0,0), (random.choice([0,2]),0,0), (4,1,-1)]
    elif genre_idx == 3: return [(1,1,1), (4,1,-1), (0,1,0), (5,1,0)]
    elif genre_idx == 4: return [(5,0,0), (3,0,0), (0,0,0), (4,0,0)]
    elif genre_idx == 5: return [(1,1,0), (4,1,-1), (0,1,0), (2,1,0)]
    return []

auto_step_idx = 0; last_auto_beat = 0
auto_event_queue = []; auto_arp_notes = []; auto_arp_idx = 0; last_auto_arp_time = 0
last_auto_octave = 0
active_tab_data = None; tab_start_time = 0; tab_event_idx = 0; tab_release_queue = []
last_click_beat = 0
live_record_tags = {} 

def apply_adsr_preset(idx):
    if idx == 0: a, d, s, r = 0.05, 0.1, 0.7, 0.8   
    elif idx == 1: a, d, s, r = 0.8, 0.2, 0.8, 1.5  
    elif idx == 2: a, d, s, r = 0.01, 0.1, 0.0, 0.1 
    elif idx == 3: a, d, s, r = 1.5, 0.1, 1.0, 2.0  
    elif idx == 4: a, d, s, r = get_val("ADSR", "ATK"), get_val("ADSR", "DEC"), get_val("ADSR", "SUS"), get_val("ADSR", "REL")
    if idx != 4: 
        set_val("ADSR", "ATK", a); set_val("ADSR", "DEC", d); set_val("ADSR", "SUS", s); set_val("ADSR", "REL", r)
    synth.set_adsr(a, d, s, r)

event_queue = []; delay_events = []; bpm = 120
arp_active = False; arp_notes = []; next_arp_notes = []; arp_idx = 0; last_arp_time = 0; arp_active_btn = None; arp_grace_time = 0 

def save_state():
    try:
        buf = bytearray(300) 
        buf[0] = 43 
        buf[1] = theory.current_key_idx
        buf[2] = bpm
        buf[3] = 1 if quantize_enabled else 0
        buf[4] = active_track
        
        for i in range(4):
            buf[5 + (i*4)] = track_states[i]["mode"]
            buf[6 + (i*4)] = track_states[i]["wave"]
            buf[7 + (i*4)] = track_states[i]["octave"] + 2
            buf[8 + (i*4)] = track_states[i]["len"] // 16
            
        buf[21] = int(get_val("ADSR", "PRESET"))
        buf[22] = int(get_val("ADSR", "ATK") * 100)
        buf[23] = int(get_val("ADSR", "DEC") * 100)
        buf[24] = int(get_val("ADSR", "SUS") * 100)
        buf[25] = int(get_val("ADSR", "REL") * 20) 
        buf[26] = int(get_val("EFFECTS", "CHORUS"))
        buf[27] = int(get_val("EFFECTS", "DELAY"))
        buf[28] = int(get_val("EFFECTS", "GLIDE") * 100)
        buf[29] = int(get_val("EFFECTS", "LFO RATE") * 10)
        buf[30] = int(get_val("EFFECTS", "TREMOLO"))
        buf[31] = int(get_val("EFFECTS", "V-LEAD"))
        buf[32] = int(get_val("EFFECTS", "VEL MIN") * 100)
        buf[33] = int(get_val("JAM", "Q-GRID"))
        buf[34] = int(get_val("JAM", "TAB"))
        buf[35] = int(get_val("JAM", "AUTO"))
        buf[36] = int(get_val("SCALE", "MODE"))
        buf[37] = int(get_val("SYS", "MIDI OUT"))
        buf[38] = int(get_val("SYS", "CLICK"))
        buf[39] = int(get_val("EFFECTS", "KBD MIN") * 100) 
        
        for ev in loop_events:
            if ev["type"] in ["PRESS", "DRUM"]:
                tag = ev.get("tag", "")
                if tag.startswith("T"):
                    try:
                        parts = tag.split("_")
                        trk, step, btn = int(parts[0][1:]), int(parts[1]), int(parts[2])
                        idx = 40 + (trk * 64) + step 
                        buf[idx] |= (1 << btn) 
                    except: pass
                    
        microcontroller.nvm[0:300] = buf
    except Exception as e: print("Save Error:", e)

def load_state():
    global bpm, quantize_enabled, active_track, auto_chords, last_auto_octave
    global loop_events, looper_state, loop_length, next_event_idx
    try:
        if len(microcontroller.nvm) >= 300 and microcontroller.nvm[0] == 43:
            theory.current_key_idx = microcontroller.nvm[1] % 12
            bpm = max(60, min(240, microcontroller.nvm[2]))
            quantize_enabled = bool(microcontroller.nvm[3])
            active_track = microcontroller.nvm[4] % 4 
            
            for i in range(4):
                track_states[i]["mode"] = microcontroller.nvm[5 + (i*4)] % len(modes)
                track_states[i]["wave"] = microcontroller.nvm[6 + (i*4)] % len(synth.waveforms)
                track_states[i]["octave"] = (microcontroller.nvm[7 + (i*4)] % 5) - 2
                track_states[i]["len"] = max(16, min(64, microcontroller.nvm[8 + (i*4)] * 16))
            
            set_val("ADSR", "PRESET", microcontroller.nvm[21] % len(menus["ADSR"][0]["list"]))
            set_val("ADSR", "ATK", microcontroller.nvm[22] / 100.0)
            set_val("ADSR", "DEC", microcontroller.nvm[23] / 100.0)
            set_val("ADSR", "SUS", microcontroller.nvm[24] / 100.0)
            set_val("ADSR", "REL", microcontroller.nvm[25] / 20.0)
            set_val("EFFECTS", "CHORUS", microcontroller.nvm[26] % len(menus["EFFECTS"][0]["list"]))
            set_val("EFFECTS", "DELAY", microcontroller.nvm[27] % len(menus["EFFECTS"][1]["list"]))
            set_val("EFFECTS", "GLIDE", microcontroller.nvm[28] / 100.0)
            set_val("EFFECTS", "LFO RATE", microcontroller.nvm[29] / 10.0)
            set_val("EFFECTS", "TREMOLO", microcontroller.nvm[30] % len(menus["EFFECTS"][4]["list"]))
            set_val("EFFECTS", "V-LEAD", microcontroller.nvm[31] % len(menus["EFFECTS"][5]["list"]))
            set_val("EFFECTS", "VEL MIN", microcontroller.nvm[32] / 100.0)
            set_val("JAM", "Q-GRID", microcontroller.nvm[33] % len(menus["JAM"][0]["list"]))
            
            t_len = len(menus["JAM"][1]["list"])
            set_val("JAM", "TAB", (microcontroller.nvm[34] % t_len) if t_len > 0 else 0)
            set_val("JAM", "AUTO", microcontroller.nvm[35] % len(menus["JAM"][2]["list"]))
            set_val("SCALE", "MODE", microcontroller.nvm[36] % len(menus["SCALE"][0]["list"]))
            set_val("SYS", "MIDI OUT", microcontroller.nvm[37] % len(menus["SYS"][0]["list"]))
            set_val("SYS", "CLICK", microcontroller.nvm[38] % len(menus["SYS"][1]["list"]))
            set_val("EFFECTS", "KBD MIN", microcontroller.nvm[39] / 100.0)
            
            apply_adsr_preset(get_val("ADSR", "PRESET"))
            synth.current_wave_idx = track_states[active_track]["wave"]
            if get_val("JAM", "AUTO") > 0: auto_chords = generate_progression(get_val("JAM", "AUTO"))

            scale_str = menus["SCALE"][0]["list"][int(get_val("SCALE", "MODE"))]
            v_lead = (get_val("EFFECTS", "V-LEAD") == 1)
            is_chorus = (get_val("EFFECTS", "CHORUS") == 1)
            beat_len = 60.0 / bpm
            q_idx = int(get_val("JAM", "Q-GRID"))
            grid_step = beat_len * [4.0, 2.0, 1.0, 0.5, 0.25][q_idx]
            
            loop_events.clear()
            for trk in range(4):
                trk_mode = modes[track_states[trk]["mode"]]
                trk_oct = track_states[trk]["octave"]
                for step in range(64):
                    mask = microcontroller.nvm[40 + (trk * 64) + step]
                    if mask != 0:
                        target_time = step * grid_step
                        for btn in range(7):
                            if mask & (1 << btn): 
                                tag = f"T{trk}_{step}_{btn}"
                                if trk_mode == "DRUM":
                                    loop_events.append({"time": target_time, "type": "DRUM", "tag": tag, "btn": btn, "track": trk})
                                else:
                                    notes, _ = theory.get_chord(btn, 0.0, 0.0, trk_oct, v_lead, scale_str)
                                    loop_events.append({"time": target_time, "type": "PRESS", "tag": tag, "notes": notes, "track": trk, "is_psych": (trk_mode=="PSYCH"), "is_chorus": is_chorus})
                                    loop_events.append({"time": target_time + (grid_step * 0.8), "type": "RELEASE", "tag": tag, "notes": [], "track": trk})
            
            if len(loop_events) > 0:
                loop_events.sort(key=lambda x: x["time"])
                max_steps = max([t["len"] for t in track_states])
                loop_length = max_steps * grid_step
                looper_state = "OFF"
                next_event_idx = 0
    except Exception as e: print("Load Error:", e)

load_state()

def execute_audio(tag, type_str, notes, now_time, is_psych=False, vol_lookup="LIVE", track_idx=0, midi_vel=None):
    global active_notes, active_midi_notes, master_vol
    is_chorus = (get_val("EFFECTS", "CHORUS") == 1)
    glide_t = get_val("EFFECTS", "GLIDE")
    delay_idx = int(get_val("EFFECTS", "DELAY"))
    
    final_vol = master_vol 
    if vol_lookup == "TRACK":
        final_vol *= track_states[track_idx].get("volume", 0.8)
        trk_wave = track_states[track_idx].get("wave", 1) 
    else: 
        final_vol *= live_synth_vol
        trk_wave = track_states[active_track].get("wave", 1) 

    if type_str == "PRESS":
        # USE KEYBOARD VELOCITY OR HUMANIZED VELOCITY
        if midi_vel is None:
            v_min = get_val("EFFECTS", "VEL MIN") 
            calc_vel = v_min + (random.random() * (1.0 - v_min))
        else:
            # Map the 0.0-1.0 keyboard input perfectly between KBD MIN and 1.0
            kbd_min = get_val("EFFECTS", "KBD MIN")
            calc_vel = kbd_min + (midi_vel * (1.0 - kbd_min))

        synth.trigger_live(tag, notes, is_psych, is_chorus, glide_t, 0.0, vol=final_vol, wave_idx=trk_wave, explicit_vel=calc_vel)
        trigger_midi(tag, notes, int(calc_vel * 127)) 
        
    elif type_str == "RELEASE": 
        synth.release_live(tag)
        release_midi(tag)        
        
    if vol_lookup == "LIVE" and not str(tag).startswith("DLY_"):
        if looper_state in ["RECORD", "OVERDUB"] and current_mode != "DRUM" and not in_step_mode:
            if looper_state == "RECORD": rec_time = now_time - loop_start_time
            else: rec_time = (now_time - playback_start) % loop_length
            
            if type_str == "PRESS":
                unique_tag = f"L{active_track}_{now_time}_{tag}"
                live_record_tags[tag] = unique_tag
                rec_tag = unique_tag
            else:
                rec_tag = live_record_tags.get(tag, tag)
            
            loop_events.append({"time": rec_time, "type": type_str, "tag": rec_tag, "notes": notes, "is_psych": is_psych, "is_chorus": is_chorus, "track": active_track})
            
    if delay_idx > 0 and current_mode != "DRUM" and not str(tag).startswith("DLY_"):
        beat_sec = 60.0 / bpm; d_time = beat_sec if delay_idx == 1 else (beat_sec/2 if delay_idx == 2 else beat_sec/4)
        delay_events.append({"time": now_time + d_time, "type": type_str, "tag": f"DLY_{tag}", "notes": notes, "is_psych": is_psych, "is_chorus": is_chorus, "track": active_track})

def refresh_step_grid(force=False):
    global step_cursor, active_track, last_viewed_page, last_viewed_track
    current_page = step_cursor // 16
    if not force and current_page == last_viewed_page and active_track == last_viewed_track: return
        
    for i in range(112): hw.step_bitmap[i % 16, i // 16] = 0
            
    page_start = current_page * 16
    page_end = page_start + 15
    track_prefix = f"T{active_track}_"
    
    for ev in loop_events:
        if ev.get("track") == active_track:
            tag = ev.get("tag", "")
            if tag.startswith(track_prefix):
                try:
                    parts = tag.split("_")
                    abs_step = int(parts[1])
                    if page_start <= abs_step <= page_end:
                        hw.step_bitmap[abs_step - page_start, int(parts[2])] = 1
                except: continue

    last_viewed_page = current_page
    last_viewed_track = active_track

def refresh_screen(chord_str="Ready", now_time=0):
    global in_step_mode, active_track, follow_mode
    if usb_high_perf: return # <--- HEADLESS BYPASS FOR USB KEYBOARD MODE
    trk_state = track_states[active_track]
    trk_mode_idx = trk_state["mode"]
    top_right_text = modes[trk_mode_idx]
    current_wave_name = synth.wave_names[trk_state["wave"]]
    
    if in_step_mode:
        hw.show_screen("STEP")
        hw.update_step_screen(step_cursor, current_wave_name, last_joy_zone, active_track, top_right_text, trk_state["len"], follow_mode)
    elif system_state == "MIXER":
        pass 
    else:
        hw.show_screen("LIVE")
        if active_tab_data:
            hw.update_screen(f"T{active_track+1}", "TAB", current_wave_name, active_tab_data['title'][:5], "PLAYING...", "TAB")
        else:
            scale_str = menus["SCALE"][0]["list"][int(get_val("SCALE", "MODE"))]
            short_scale = "MAJ" if scale_str == "MAJOR" else scale_str[:4].strip()
            trk_octave = trk_state["octave"]
            track_str = f"T{active_track+1}"
            key_str = f"{theory.get_key_name()}{'+' if trk_octave >= 0 else ''}{trk_octave}"
            hw.update_screen(track_str, key_str, current_wave_name, chord_str, top_right_text, short_scale)

def refresh_menu_screen():
    batt = hw.read_battery_pct()
    
    if current_menu_level == "ROOT":
        hw.update_menu_screen("MENU", f"{menu_idx+1}/{len(menus['ROOT'])}", menus['ROOT'][menu_idx], "[ENTER]", batt)
    else:
        item = menus[current_menu_level][menu_idx]
        if item["type"] == "back": 
            hw.update_menu_screen(f"{current_menu_level}", "", "<- RETURN", "BACK", batt)
        else:
            if item["type"] == "list":
                display_val = item["list"][int(item["val"])]
            elif item["type"] == "action":
                display_val = ">>>"
            else:
                display_val = f"{item['val']:.2f}"
                
            if item["id"] == "PRESET" and display_val == "MANUAL":
                display_val = f"M: {get_val('ADSR','ATK'):.1f} {get_val('ADSR','DEC'):.1f} {get_val('ADSR','SUS'):.1f} {get_val('ADSR','REL'):.1f}"
                
            bottom_text = "[ENTER]" if item["type"] == "action" else ("[EDIT]" if menu_editing else "[SCROLL]")
            hw.update_menu_screen(f"{current_menu_level}", f"{menu_idx+1}/{len(menus[current_menu_level])}", f"{item['id']} {display_val}", bottom_text, batt)

def apply_joystick_mode(x, y):
    mode = getattr(theory, "joystick_mode", 0)
    if mode == 0: return x, y
    elif mode == 1: return x * 1.8, y * 1.8
    elif mode == 2: 
        def quant(v):
            if v > 0.5: return 1
            if v < -0.5: return -1
            return 0
        return quant(x), quant(y)
    return x, y

def panic():
    synth.release_all()
    delay_events.clear()
    event_queue.clear()
    auto_event_queue.clear()
    release_all_midi()

hj_last_midi = -1
hj_last_lane = 3 

def get_hero_lane(midi_note):
    global hj_last_midi, hj_last_lane
    
    if hj_last_midi == -1:
        hj_last_midi = midi_note
        hj_last_lane = 3
        return hj_last_lane
        
    delta_pitch = midi_note - hj_last_midi
    delta_lane = 0
    if delta_pitch > 0:
        if delta_pitch <= 2: delta_lane = 1       
        elif delta_pitch <= 5: delta_lane = 2     
        else: delta_lane = 3                      
    elif delta_pitch < 0:
        if delta_pitch >= -2: delta_lane = -1
        elif delta_pitch >= -5: delta_lane = -2
        else: delta_lane = -3
        
    new_lane = max(0, min(6, hj_last_lane + delta_lane))
    hj_last_midi = midi_note
    hj_last_lane = new_lane
    return new_lane

refresh_screen(now_time=time.monotonic())

while True:
    now = time.monotonic()
    check_usb_keyboard(now)
    master_vol = 1.0

    click_mode = get_val("SYS", "CLICK")
    if click_mode > 0 and onboard_led:
        beat_dur = 60.0 / bpm
        current_beat = int(now / beat_dur)
        if current_beat > last_click_beat:
            last_click_beat = current_beat
            if click_mode == 2: synth.play_drum("HAT") 
        onboard_led.value = ((now % beat_dur) / beat_dur) < 0.10
    else:
        if onboard_led: onboard_led.value = False
        last_click_beat = int(now / (60.0 / bpm))
        
    if hasattr(synth, 'update_tremolo'): synth.update_tremolo(get_val("EFFECTS", "TREMOLO") == 1)
        
    current_mode_idx = track_states[active_track]["mode"]
    current_mode = modes[current_mode_idx]
    v_lead = (get_val("EFFECTS", "V-LEAD") == 1)
    current_scale_string = menus["SCALE"][0]["list"][int(get_val("SCALE", "MODE"))]

    # ==========================================
    # ---> LEAD MODE TILT PITCH BEND <---
    # ==========================================
    if not hasattr(hw, 'last_print_time'): hw.last_print_time = now
    do_print = (now - hw.last_print_time) > 0.5 

    tilt_x, tilt_y, tilt_z = hw.read_tilt()

    # ---> USING X-AXIS <---
    active_tilt = tilt_x 

    if current_mode == "LEAD" and system_state not in ["MENU", "HEROJAM", "EARTRAINER"]:
        if abs(active_tilt) < 1.5:
            target_pb = 8192
        else:
            mapped_val = int(((active_tilt + 9.8) / 19.6) * 16383)
            target_pb = max(0, min(16383, mapped_val))
    else:
        target_pb = 8192

    if not hasattr(synth, 'current_pitch_bend'): synth.current_pitch_bend = 8192
    if not hasattr(synth, 'pb_base_freqs'): synth.pb_base_freqs = {} 
    
    semitone_offset = ((target_pb - 8192) / 8192.0) * 2.0
    synth.bend_multiplier = 2.0 ** (semitone_offset / 12.0)
    
    active_note_ids = set()

    # 2. Instantly bend any LIVE notes playing
    for tag, track_data in synth.active_live.items():
        # ---> FIX: Safely extract the list of Note objects from the dict <---
        note_list = track_data.get("notes", []) if isinstance(track_data, dict) else track_data
        
        for n in note_list:
            nid = id(n)
            active_note_ids.add(nid)
            
            base_freq = synth.glide_targets.get(n)
            
            # If Glide is OFF (0.0), track the pristine frequency manually
            if base_freq is None:
                if nid not in synth.pb_base_freqs:
                    synth.pb_base_freqs[nid] = n.frequency 
                base_freq = synth.pb_base_freqs[nid]
                
            n.frequency = base_freq * synth.bend_multiplier

    # 3. Clean up memory
    keys_to_delete = [k for k in synth.pb_base_freqs.keys() if k not in active_note_ids]
    for k in keys_to_delete:
        del synth.pb_base_freqs[k]

    # 4. Route data out to external hardware/DAWs
    if synth.current_pitch_bend != target_pb:
        synth.current_pitch_bend = target_pb
        if get_val("SYS", "MIDI OUT") == 1 and midi is not None:
            try: midi.send(PitchBend(target_pb))
            except: pass
    # ==========================================

    # ==========================================
    # ---> GLIDE (PORTAMENTO) ENGINE <---
    # ==========================================
    g_val = get_val("EFFECTS", "GLIDE")
    # You are right! Glide is 0.0 when off, so this safely skips if disabled.
    if g_val > 0.0:
        for tag, track_data in synth.active_live.items():
            # ---> FIX: Applied the exact same dictionary fix here! <---
            note_list = track_data.get("notes", []) if isinstance(track_data, dict) else track_data
            
            for n in note_list:
                base_target = synth.glide_targets.get(n)
                if base_target:
                    current_bend = getattr(synth, 'bend_multiplier', 1.0)
                    actual_target = base_target * current_bend
                    
                    if n.frequency != actual_target:
                        diff = actual_target - n.frequency
                        if abs(diff) < 0.5: 
                            n.frequency = actual_target
                        else: 
                            n.frequency += diff * (0.01 / g_val)
    
    if system_state == "EARTRAINER":
        if ear_state == "WAIT" and now > ear_timer:
            ear_target = random.randint(0, 6)
            ear_state = "PLAY_ROOT"; ear_timer = now + 0.5
        elif ear_state == "PLAY_ROOT" and now > ear_timer:
            root_midi = 60 + theory.current_key_idx
            execute_audio("EAR_ROOT", "PRESS", [root_midi], now)
            ear_state = "PLAY_CHORD"; ear_timer = now + 1.0
            refresh_screen("LISTEN...", now)
        elif ear_state == "PLAY_CHORD" and now > ear_timer:
            execute_audio("EAR_ROOT", "RELEASE", [], now)
            notes, _ = theory.get_chord(ear_target, 0, 0, 0, False, current_scale_string)
            execute_audio("EAR_CHORD", "PRESS", notes, now)
            ear_state = "STOP_CHORD"; ear_timer = now + 1.5
        elif ear_state == "STOP_CHORD" and now > ear_timer:
            execute_audio("EAR_CHORD", "RELEASE", [], now)
            ear_state = "GUESS"; refresh_screen("GUESS 1-7", now)
        elif ear_state == "SUCCESS" and now > ear_timer:
            ear_state = "WAIT"

    if current_mode == "REPEAT" and len(last_buttons_state) > 0 and not in_step_mode:
        repeat_interval = (60.0 / bpm) / 2
        if now - last_repeat_time >= repeat_interval:
            for b in last_buttons_state:
                execute_audio(f"BTN_{b}", "RELEASE", [], now)
                notes, _ = theory.get_chord(b, chord_joy_x, chord_joy_y, current_octave, v_lead, current_scale_string)
                execute_audio(f"BTN_{b}", "PRESS", notes, now)
            last_repeat_time = now
            
    if looper_state == "RECORD" and looper_bars > 0:
        target_length = looper_bars * (60.0 / bpm) * 4
        if (now - loop_start_time) >= target_length:
            looper_state = "PLAY"
            loop_length = target_length
            playback_start = now
            next_event_idx = 0
            prefix = "Q-" if quantize_enabled else ""
            if quantize_enabled:
                q_idx = int(get_val("JAM", "Q-GRID"))
                grid_step = (60.0 / bpm) * [4.0, 2.0, 1.0, 0.5, 0.25][q_idx]
                for i, ev in enumerate(loop_events):
                    if ev["type"] == "PRESS":
                        q_press = round(ev["time"] / grid_step) * grid_step
                        ev["time"] = q_press
                        for j in range(i + 1, len(loop_events)):
                            if loop_events[j]["type"] == "RELEASE" and loop_events[j]["tag"] == ev["tag"]:
                                orig_rel = loop_events[j]["time"]
                                loop_events[j]["time"] = min(loop_length - 0.01, max(q_press + grid_step, round(orig_rel / grid_step) * grid_step))
                                break
            loop_events.sort(key=lambda x: x["time"])
            refresh_screen(f"{prefix}LOOP", now)
            
    # ---> SEQUENCER PLAYBACK ENGINE <---
    if looper_state in ["PLAY", "OVERDUB", "RECORD"] and loop_length > 0:
        loop_pos = (now - playback_start) % loop_length
        if in_step_mode and follow_mode:
            beat_len = 60.0 / bpm
            q_idx = int(get_val("JAM", "Q-GRID"))
            grid_step = beat_len * [4.0, 2.0, 1.0, 0.5, 0.25][q_idx]
            play_step = int(loop_pos / grid_step)
            current_play_page = play_step // 16
            if current_play_page != last_page_seen:
                step_cursor = current_play_page * 16 
                refresh_step_grid(); refresh_screen(now_time=now)
                last_page_seen = current_play_page
        
        if loop_pos < last_loop_pos: next_event_idx = 0
            
        while next_event_idx < len(loop_events) and loop_events[next_event_idx]["time"] <= loop_pos:
            ev = loop_events[next_event_idx]
            next_event_idx += 1
            if track_states[ev["track"]].get("muted", False): continue
            
            if ev["type"] == "PRESS": 
                execute_audio(ev["tag"], "PRESS", ev.get("notes", []), now, is_psych=ev.get("is_psych", False), vol_lookup="TRACK", track_idx=ev["track"])
            elif ev["type"] == "RELEASE": 
                execute_audio(ev["tag"], "RELEASE", [], now, vol_lookup="TRACK", track_idx=ev["track"])
            elif ev["type"] == "DRUM":
                drums = ["KICK", "SNARE", "HAT", "TOM", "RIDE", "CRASH", "CLAP"]
                btn_idx = ev.get("btn", 0)
                if btn_idx < len(drums): 
                    trk_vol = master_vol * track_states[ev["track"]].get("volume", 0.8)
                    synth.play_drum(drums[btn_idx], vol=trk_vol)
        last_loop_pos = loop_pos

    # ==========================================
    # ---> HERO-JAM ARCADE MODE <---
    # ==========================================
    if system_state == "HEROJAM":
        if hero_state == "SELECT":
            hw.show_screen("LIVE") 
            song_name = tab_list[hero_tab_idx] if len(tab_list) > 1 else "NO SONGS"
            hw.update_screen("HERO", "JAM", "U/D: SEL", "CLICK 2 PLAY", song_name, "SONG")
            
            jx, jy = hw.read_joystick()
            if jy > 0.6 and now > getattr(hw, "hj_scroll_timer", 0):
                hero_tab_idx = max(1, hero_tab_idx - 1)
                hw.hj_scroll_timer = now + 0.3
            elif jy < -0.6 and now > getattr(hw, "hj_scroll_timer", 0):
                hero_tab_idx = min(len(tab_list)-1, hero_tab_idx + 1) 
                hw.hj_scroll_timer = now + 0.3
            
            current_joy_sw = hw.joy_sw.value
            if not current_joy_sw and joy_sw_last:
                joy_sw_press_time = now; joy_sw_handled = True
                if len(tab_list) > 1:
                    try:
                        with open("/tabs/" + tab_files[hero_tab_idx - 1], "r") as f:
                            active_tab_data = json.load(f)
                        hero_state = "PLAY"
                        hw.display.root_group = hero_engine.group 
                        hero_engine.reset_score()
                        hero_start_time = now + 2.0 
                        hero_event_idx = 0
                        hero_hits = 0
                        hero_total = len(active_tab_data["events"])
                        hj_last_midi, hj_last_lane = -1, -1 
                        hero_streak = 0
                        hero_mult = 1
                        hero_score = 0
                        hero_engine.update_combo(0, 1)
                        theory.game_paused = False
                    except Exception as e: print("Tab Load Error:", e)
            joy_sw_last = current_joy_sw
            continue

        elif hero_state == "PLAY":
            if hw.display.root_group != hero_engine.group: hw.display.root_group = hero_engine.group
            
            fn1_btn.update(); fn2_btn.update()
            for db in note_btn_debouncers: db.update()
            
            if fn1_btn.just_pressed: 
                active_tab_data = None 
                system_state = "MENU"
                synth.release_all()
                hw.show_screen("LIVE") 
                refresh_menu_screen()
                continue
                
            if fn2_btn.just_pressed: 
                theory.game_paused = not getattr(theory, "game_paused", False)
                if theory.game_paused: 
                    synth.release_all()
                    hero_pause_start = now 
                else:
                    pause_duration = now - hero_pause_start
                    hero_start_time += pause_duration
                    for note in hero_engine.active_notes:
                        if note["active"]:
                            note["target_time"] += pause_duration
            
            if not getattr(theory, "game_paused", False):
                fall_time = 2.0
                elapsed = now - hero_start_time
                
                while hero_event_idx < hero_total:
                    ev = active_tab_data["events"][hero_event_idx]
                    if elapsed >= (ev["time"] - fall_time):
                        if len(ev["notes"]) > 0:
                            root_midi = 60 + theory.current_key_idx
                            lane = get_hero_lane(ev["notes"][0])
                            hero_engine.spawn_note(lane, hero_start_time + ev["time"], hero_event_idx)
                        hero_event_idx += 1
                    else: break
                        
                if now - hero_last_draw > 0.033:
                    missed_notes = hero_engine.update(now, fall_duration=fall_time)
                    for m_idx in missed_notes: 
                        hero_engine.draw_score(m_idx, hero_total, False)
                        hero_streak = 0; hero_mult = 1; hero_engine.update_combo(0, 1)
                    hero_last_draw = now

                hit_window = 0.15 
                for i in range(7):
                    if note_btn_debouncers[i].just_pressed:
                        hit_successful = False
                        for note in hero_engine.active_notes:
                            if note["active"] and note["lane"] == i:
                                if abs(note["target_time"] - now) <= hit_window:
                                    hero_engine.hide_note(note)
                                    hero_engine.draw_score(note["idx"], hero_total, True) 
                                    
                                    hero_hits += 1
                                    hero_streak += 1
                                    if hero_streak >= 30: hero_mult = 4
                                    elif hero_streak >= 20: hero_mult = 3
                                    elif hero_streak >= 10: hero_mult = 2
                                    hero_score += (10 * hero_mult) 
                                    hero_engine.update_combo(hero_streak, hero_mult)
                                    
                                    original_notes = active_tab_data["events"][note["idx"]]["notes"]
                                    synth.trigger_live(f"HJ_{i}", original_notes, vol=master_vol)
                                    hit_successful = True
                                    break
                                    
                        if not hit_successful:
                            hero_streak = 0; hero_mult = 1; hero_engine.update_combo(0, 1) 
                            
                    elif note_btn_debouncers[i].just_released:
                        synth.release_live(f"HJ_{i}")

                if hero_event_idx >= hero_total:
                    any_active = any(n["active"] for n in hero_engine.active_notes)
                    if not any_active and elapsed > active_tab_data["events"][-1]["time"] + 0.5:
                        hero_state = "END"
        
        elif hero_state == "END":
            hw.show_screen("LIVE") 
            pct = int((hero_hits / hero_total) * 100) if hero_total > 0 else 0
            hw.update_screen("HERO", "END", f"PTS: {hero_score}", f"{pct}% HIT", "PRESS ANY", "BTN")            
            for db in note_btn_debouncers: db.update()
            
            any_pressed = (hw.joy_sw.value == False)
            for db in note_btn_debouncers:
                if db.just_pressed: any_pressed = True
            
            if any_pressed:
                active_tab_data = None
                hero_state = "SELECT"
                joy_sw_handled = True

        continue 

    if active_tab_data and system_state == "PLAY":
        elapsed = now - tab_start_time
        while tab_event_idx < len(active_tab_data["events"]):
            ev = active_tab_data["events"][tab_event_idx]
            if elapsed >= ev["time"]:
                tag = f"TAB_TRK_{tab_event_idx}"
                note_dur = ev.get("duration", 0.35) 
                synth.trigger_loop(tag, ev["notes"], False, (get_val("EFFECTS", "CHORUS")==1))
                trigger_midi(tag, ev["notes"])
                tab_release_queue.append({"time": now + note_dur + 0.10, "tag": tag}) 
                tab_event_idx += 1
            else: break
        if tab_event_idx >= len(active_tab_data["events"]):
            tab_start_time = now; tab_event_idx = 0

    for tr in tab_release_queue[:]:
        if now >= tr["time"]:
            synth.release_loop(tr["tag"]); release_midi(tr["tag"]) 
            tab_release_queue.remove(tr)

    auto_idx = int(get_val("JAM", "AUTO"))
    if auto_idx > 0 and system_state == "PLAY":
        measure_sec = (60.0 / bpm) * 4 
        if now - last_auto_beat >= measure_sec:
            if len(auto_chords) > 0:
                if current_octave != last_auto_octave: theory.last_chord_notes = []; last_auto_octave = current_octave
                if auto_step_idx == 0: theory.last_chord_notes = [] 
                    
                b, x, y = auto_chords[auto_step_idx]
                notes, c_name = theory.get_chord(b, x, y, current_octave, v_lead, current_scale_string)
                if not active_tab_data: refresh_screen(f"AUTO: {c_name}", now)
                
                auto_mode = current_mode if current_mode != "DRUM" else "ONESHOT"
                for k in list(synth.active_loop.keys()):
                    if str(k).startswith("AUTO_TRK") or str(k).startswith("AUTO_ARP"): 
                        synth.release_loop(k); release_midi(k) 
                auto_event_queue.clear()       
                
                if auto_mode == "ONESHOT" or auto_mode == "PSYCH":
                    synth.trigger_loop("AUTO_TRK", notes, is_psych=(auto_mode=="PSYCH"), is_chorus=(get_val("EFFECTS", "CHORUS")==1))
                    trigger_midi("AUTO_TRK", notes) 
                elif auto_mode == "STRUM":
                    delay = 0.0
                    for i, note in enumerate(notes):
                        auto_event_queue.append({"time": now + delay, "tag": f"AUTO_TRK_{i}", "notes": [note]})
                        delay += 0.04
                elif auto_mode == "ARPEGGIO":
                    auto_arp_notes = notes; auto_arp_idx = 0
                auto_step_idx = (auto_step_idx + 1) % len(auto_chords)
            last_auto_beat = now

    g_val = get_val("EFFECTS", "GLIDE")
    if g_val > 0.0:
        for tag, notes in synth.active_live.items():
            for n in notes:
                base_target = synth.glide_targets.get(n)
                if base_target:
                    # Grab the current bend multiplier (default to 1.0 if not bending)
                    current_bend = getattr(synth, 'bend_multiplier', 1.0)
                    
                    # The actual target frequency includes your physical tilt!
                    actual_target = base_target * current_bend
                    
                    if n.frequency != actual_target:
                        diff = actual_target - n.frequency
                        if abs(diff) < 0.5: 
                            n.frequency = actual_target
                        else: 
                            n.frequency += diff * (0.01 / g_val)

    for event in delay_events[:]:
        if now >= event["time"]:
            if event["type"] == "PRESS": synth.trigger_delay(event["tag"], event["notes"], event["is_psych"], event["is_chorus"])
            elif event["type"] == "RELEASE": synth.release_delay(event["tag"])
            delay_events.remove(event)

    for event in event_queue[:]:
        if now >= event["time"]: execute_audio(event["tag"], "PRESS", event["notes"], now); event_queue.remove(event)

    for event in auto_event_queue[:]:
        if now >= event["time"]:
            synth.trigger_loop(event["tag"], event["notes"], False, (get_val("EFFECTS", "CHORUS")==1))
            trigger_midi(event["tag"], event["notes"])
            auto_event_queue.remove(event)

    if auto_idx > 0 and len(auto_arp_notes) > 0 and (current_mode == "ARPEGGIO" or current_mode == "DRUM"):
        if current_mode == "ARPEGGIO" and (now - last_auto_arp_time) >= ((60.0 / bpm) / 2):
            synth.release_loop("AUTO_ARP"); release_midi("AUTO_ARP")
            synth.trigger_loop("AUTO_ARP", [auto_arp_notes[auto_arp_idx]], False, (get_val("EFFECTS", "CHORUS")==1))
            trigger_midi("AUTO_ARP", [auto_arp_notes[auto_arp_idx]])
            auto_arp_idx = (auto_arp_idx + 1) % len(auto_arp_notes)
            last_auto_arp_time = now

    if current_mode == "ARPEGGIO":
        if arp_grace_time > 0 and now > arp_grace_time:
            if len(set([db for db in note_btn_debouncers if db.current_state])) == 0: 
                arp_active = False; next_arp_notes = []; execute_audio("ARP", "RELEASE", [], now)
            arp_grace_time = 0

        if arp_active:
            if (now - last_arp_time) >= ((60.0 / bpm) / 2):
                if arp_idx == 0 and len(next_arp_notes) > 0: arp_notes = next_arp_notes
                execute_audio("ARP", "RELEASE", [], now) 
                if len(arp_notes) > 0:
                    if arp_idx >= len(arp_notes): arp_idx = 0 
                    execute_audio("ARP", "PRESS", [arp_notes[arp_idx]], now) 
                    arp_idx = (arp_idx + 1) % len(arp_notes)
                last_arp_time = now

    fn1_btn.update(); fn2_btn.update(); fn3_btn.update()
    fn1_held, fn2_held, fn3_held = fn1_btn.current_state, fn2_btn.current_state, fn3_btn.current_state
    if system_state in ["EARTRAINER", "HEROJAM"]:
        if fn1_btn.just_pressed: 
            system_state = "MENU"
            synth.release_all()
            refresh_menu_screen()
            continue
        if fn2_btn.just_pressed: 
            game_paused = not getattr(theory, "game_paused", False)
            theory.game_paused = game_paused
            if game_paused: 
                synth.release_all()
    if fn1_held and fn2_held and fn3_held:
        panic()
        refresh_screen("PANIC", now)
        continue
    if fn3_btn.just_released and system_state == "PLAY" and not in_step_mode:
        quantize_enabled = not quantize_enabled
        refresh_screen("Q-ON" if quantize_enabled else "Q-OFF", now)

    joy_x_raw, joy_y_raw = hw.read_joystick()       

    # ---> ISOLATE CHORD ENGINE FROM UI <---
    if fn1_held or fn2_held or fn3_held or system_state in ["MENU", "MIXER"]:
        chord_joy_x, chord_joy_y = 0.0, 0.0
    elif current_mode == "PSYCH":
        synth.psych_lfo.rate = max(0.1, min(15.0, get_val("EFFECTS", "LFO RATE") + (joy_x_raw * 5.0)))
        synth.psych_lfo.offset = max(1200, min(4000, 2600 - (joy_y_raw * 1400))) 
        chord_joy_x, chord_joy_y = 0.0, 0.0
        if hasattr(synth, 'update_filter'): synth.update_filter(8000, 0.7) 
    else: 
        chord_joy_x, chord_joy_y = apply_joystick_mode(joy_x_raw, joy_y_raw)
        if hasattr(synth, 'update_filter'): synth.update_filter(8000, 0.7) 

    current_joy_zone = get_joy_zone(chord_joy_x, chord_joy_y) 
    if current_joy_zone != last_joy_zone:
        if len(last_buttons_state) > 0 and current_mode not in ["DRUM", "PSYCH", "EARTRAINER"] and not in_step_mode:
            for btn_idx in last_buttons_state:
                notes, chord_name = theory.get_chord(btn_idx, chord_joy_x, chord_joy_y, current_octave, v_lead, current_scale_string)
                if system_state == "PLAY" and not active_tab_data: refresh_screen(chord_name, now)
                if current_mode == "ONESHOT" or current_mode == "LEAD": execute_audio(f"BTN_{btn_idx}", "PRESS", notes, now, is_psych=False)
                elif current_mode == "STRUM":
                    event_queue[:] = [e for e in event_queue if not e["tag"].startswith(f"BTN_{btn_idx}")]
                    keys_to_release = [k for k in synth.active_live.keys() if str(k).startswith(f"BTN_{btn_idx}")]
                    for k in keys_to_release: execute_audio(k, "RELEASE", [], now)
                    delay = 0.0
                    for i, note in enumerate(notes): event_queue.append({"time": now + delay, "tag": f"BTN_{btn_idx}_{i}", "notes": [note]}); delay += 0.04 
                elif current_mode == "ARPEGGIO":
                    if arp_active_btn == btn_idx: next_arp_notes = notes 
        last_joy_zone = current_joy_zone
    
    joy_x_delta, joy_y_delta = 0, 0
    curr_x_state = 1 if joy_x_raw > 0.6 else (-1 if joy_x_raw < -0.6 else 0)
    if curr_x_state != 0:
        if joy_x_state != curr_x_state:
            joy_x_delta = curr_x_state
            joy_x_timer = now + 0.4 
        elif now > joy_x_timer:
            joy_x_delta = curr_x_state
            joy_x_timer = now + 0.1 
    joy_x_state = curr_x_state

    curr_y_state = 1 if joy_y_raw > 0.6 else (-1 if joy_y_raw < -0.6 else 0)
    if curr_y_state != 0:
        if joy_y_state != curr_y_state:
            joy_y_delta = curr_y_state
            joy_y_timer = now + 0.4
        elif now > joy_y_timer:
            joy_y_delta = curr_y_state
            joy_y_timer = now + 0.1
    joy_y_state = curr_y_state

    if joy_x_delta != 0 or joy_y_delta != 0:
        if system_state == "MIXER":
            if joy_x_delta != 0:
                mixer_cursor = max(0, min(4, mixer_cursor + joy_x_delta))
                volumes = [t.get("volume", 0.8) for t in track_states] + [live_synth_vol]
                mutes = [t.get("muted", False) for t in track_states] 
                hw.update_mixer_screen(volumes, mutes, mixer_cursor)  
                
            if joy_y_delta != 0:
                vol_change = joy_y_delta * -0.10 
                if mixer_cursor < 4:
                    cur_v = track_states[mixer_cursor].get("volume", 0.8)
                    track_states[mixer_cursor]["volume"] = max(0.0, min(1.0, cur_v + vol_change))
                elif mixer_cursor == 4:
                    live_synth_vol = max(0.0, min(1.0, live_synth_vol + vol_change))
                    
                volumes = [t.get("volume", 0.8) for t in track_states] + [live_synth_vol]
                mutes = [t.get("muted", False) for t in track_states] 
                hw.update_mixer_screen(volumes, mutes, mixer_cursor)  

            current_joy_sw = hw.joy_sw.value
            if not current_joy_sw and joy_sw_last:
                system_state = "PLAY"
                joy_sw_handled = True
                refresh_screen(now_time=now)

        elif system_state == "MENU":
            if menu_editing and joy_x_delta != 0:
                item = menus[current_menu_level][menu_idx]
                if item["type"] == "num":
                    item["val"] += joy_x_delta * item["step"]
                    item["val"] = max(item["min"], min(item["max"], item["val"])) 
                elif item["type"] == "list":
                    item["val"] = int(item["val"] + joy_x_delta) % len(item["list"])
                
                if item["id"] == "PRESET": apply_adsr_preset(item["val"])
                elif item["id"] in ["ATK", "DEC", "SUS", "REL"]: set_val("ADSR", "PRESET", 4); apply_adsr_preset(4)
                elif item["id"] == "TAB":
                    if item["val"] == 0: 
                        active_tab_data = None
                        for k in list(synth.active_loop.keys()):
                            if str(k).startswith("TAB_TRK"): synth.release_loop(k); release_midi(k) 
                    else:
                        try:
                            with open("/tabs/" + tab_files[int(item["val"]) - 1], "r") as f: active_tab_data = json.load(f)
                            tab_start_time = now; tab_event_idx = 0
                        except Exception: active_tab_data = None
            elif not menu_editing and joy_y_delta != 0: 
                if current_menu_level == "ROOT": menu_idx = (menu_idx + joy_y_delta) % len(menus["ROOT"])
                else: menu_idx = (menu_idx + joy_y_delta) % len(menus[current_menu_level])
            refresh_menu_screen()
            
        else: # System is in PLAY state
            if looper_state == "WAITING" and joy_y_delta != 0:
                looper_bars = max(0, min(8, looper_bars - joy_y_delta))
                refresh_screen(f"WAIT: {looper_bars} BARS" if looper_bars > 0 else "WAIT: FREE", now)

            elif fn1_held and joy_y_delta != 0: 
                theory.set_key(-joy_y_delta); refresh_screen(now_time=now)
                
            elif fn2_held and joy_y_delta != 0: 
                track_states[active_track]["octave"] = max(-2, min(1, track_states[active_track]["octave"] - joy_y_delta))
                theory.last_chord_notes = []; refresh_screen(now_time=now)
                
            elif fn3_held and joy_y_delta != 0: 
                scale_item = menus["SCALE"][0]
                scale_item["val"] = (scale_item["val"] - joy_y_delta) % len(scale_item["list"])
                refresh_screen(now_time=now)

            elif fn1_held and joy_x_delta != 0: 
                new_mode = (track_states[active_track]["mode"] + joy_x_delta) % len(modes)
                track_states[active_track]["mode"] = new_mode
                arp_active = False; synth.release_all(); release_all_midi()
                refresh_screen(now_time=now)
                
            elif fn2_held and joy_x_delta != 0: 
                track_states[active_track]["wave"] = (track_states[active_track]["wave"] + joy_x_delta) % len(synth.waveforms)
                synth.current_wave_idx = track_states[active_track]["wave"]
                refresh_screen(now_time=now)
            
            elif fn3_held and joy_x_delta != 0 and not in_step_mode: 
                bpm = max(60, min(240, bpm + (joy_x_delta * 5)))
                refresh_screen(f"BPM: {bpm}", now)
            elif fn3_held and joy_x_delta != 0 and in_step_mode: 
                max_steps = track_states[active_track]["len"]
                old_page = step_cursor // 16
                step_cursor = (step_cursor + joy_x_delta) % max_steps
                if (step_cursor // 16) != old_page: refresh_step_grid()
                refresh_screen(now_time=now)

    current_joy_sw = hw.joy_sw.value
    if not current_joy_sw and joy_sw_last: # Pressed Down!
        joy_sw_press_time = now; joy_sw_handled = False
        
        if fn1_held: 
            save_state()
            hw.show_screen("LIVE") 
            hw.update_menu_screen("SYS", "CONFIG", "SAVED!", "TO MEMORY") 
            time.sleep(1)
            if system_state == "MENU": refresh_menu_screen()
            else: refresh_screen(now_time=now)
            joy_sw_handled = True
            
        elif fn2_held: 
            if in_step_mode:
                follow_mode = not follow_mode
                refresh_screen("FOLLOW ON" if follow_mode else "FOLLOW OFF", now)
            else:
                theory.joystick_mode = (theory.joystick_mode + 1) % 3
                modes_text = ["JOY: DEFAULT", "JOY: EXTEND", "JOY: CHROM"]
                refresh_screen(modes_text[theory.joystick_mode], now)
            joy_sw_handled = True
            
        elif fn3_held and system_state == "PLAY": 
            if looper_state in ["PLAY", "RECORD", "OVERDUB"]:
                looper_state = "OFF"
                synth.release_all(); release_all_midi()
                delay_events.clear()
                event_queue.clear()
                auto_event_queue.clear()
                refresh_screen("STOPPED", now)
                gc.collect()
            else:
                looper_state = "PLAY"
                playback_start = now
                last_loop_pos = 0; next_event_idx = 0
                beat_len = 60.0 / bpm
                q_idx = int(get_val("JAM", "Q-GRID"))
                grid_step = beat_len * [4.0, 2.0, 1.0, 0.5, 0.25][q_idx]
                max_steps = max([t["len"] for t in track_states])
                loop_length = max_steps * grid_step
                refresh_screen("PLAYING", now)
            joy_sw_handled = True
            
    elif not current_joy_sw and not joy_sw_last:
        if not joy_sw_handled and (now - joy_sw_press_time) > 0.6:
            joy_sw_handled = True
            if system_state == "PLAY": system_state = "MENU"; menu_editing = False; current_menu_level = "ROOT"; menu_idx = 0; refresh_menu_screen()
            else: system_state = "PLAY"; tab_start_time = now; refresh_screen(now_time=now)
            gc.collect()
    elif current_joy_sw and not joy_sw_last:
        if not joy_sw_handled:
            if system_state == "MIXER":
                system_state = "PLAY"
                refresh_screen(now_time=now)
            elif system_state == "MENU":
                if current_menu_level == "ROOT":
                    current_menu_level = menus["ROOT"][menu_idx].replace(" >", "")
                    menu_idx = 0
                else:
                    item = menus[current_menu_level][menu_idx]
                    if item["type"] == "back": 
                        current_menu_level = "ROOT"; menu_idx = 0
                    elif item["type"] == "action":
                        system_state = item["val"]
                        game_paused = False
                        if system_state == "HEROJAM":
                            hero_state = "SELECT"      
                            hero_tab_idx = 1
                            tab_start_time = now
                            tab_event_idx = 0
                        elif system_state == "EARTRAINER":
                            ear_state = "WAIT"
                            ear_timer = now + 1.0
                    else: 
                        menu_editing = not menu_editing
                refresh_menu_screen()
                
            elif system_state == "PLAY":
                if in_step_mode:
                    max_steps = track_states[active_track]["len"]
                    old_page = step_cursor // 16
                    step_cursor = (step_cursor + 1) % max_steps
                    if (step_cursor // 16) != old_page: refresh_step_grid()
                    refresh_screen(now_time=now)
                else:
                    prefix = "Q-" if quantize_enabled else ""
                    if looper_state == "OFF": 
                        looper_state = "WAITING"; looper_bars = 0; refresh_screen("WAIT: FREE", now)
                    elif looper_state == "WAITING":
                        looper_state = "RECORD"; loop_events = []; loop_start_time = now; refresh_screen(f"{prefix}REC", now)
                    elif looper_state == "RECORD":
                        looper_state = "PLAY"; raw_loop_length = now - loop_start_time
                        if quantize_enabled:
                            beat_len = 60.0 / bpm
                            loop_length = round(raw_loop_length / beat_len) * beat_len
                            if loop_length == 0: loop_length = beat_len 
                            q_idx = int(get_val("JAM", "Q-GRID"))
                            multipliers = [4.0, 2.0, 1.0, 0.5, 0.25]
                            grid_step = beat_len * multipliers[q_idx]
                            for i, ev in enumerate(loop_events):
                                if ev["type"] == "PRESS":
                                    q_press = round(ev["time"] / grid_step) * grid_step
                                    ev["time"] = q_press
                                    for j in range(i + 1, len(loop_events)):
                                        if loop_events[j]["type"] == "RELEASE" and loop_events[j]["tag"] == ev["tag"]:
                                            orig_rel = loop_events[j]["time"]
                                            loop_events[j]["time"] = min(loop_length - 0.01, max(q_press + grid_step, round(orig_rel / grid_step) * grid_step))
                                            break
                            loop_events.sort(key=lambda x: x["time"])
                        else: loop_length = raw_loop_length
                        
                        playback_start = now
                        next_event_idx = 0 
                        refresh_screen(f"{prefix}LOOP", now)
                    elif looper_state == "PLAY": 
                        looper_state = "OVERDUB"
                        refresh_screen(f"{prefix}OVERDUB", now)
                    elif looper_state == "OVERDUB": 
                        looper_state = "PLAY"
                        loop_events.sort(key=lambda x: x["time"])
                        refresh_screen(f"{prefix}LOOP", now)
    joy_sw_last = current_joy_sw

    current_set = set()
    for i, db in enumerate(note_btn_debouncers):
        db.update(); 
        if db.current_state: current_set.add(i)
        
    just_pressed = current_set - last_buttons_state
    just_released = last_buttons_state - current_set
    
    for btn_idx in just_released:
        if current_mode == "DRONE": 
            pass 
        else:
            execute_audio(f"BTN_{btn_idx}", "RELEASE", [], now)
            if current_mode == "ARPEGGIO" and btn_idx == arp_active_btn: arp_grace_time = now + 0.15 
            elif current_mode not in ["DRUM", "ARPEGGIO", "EARTRAINER"]:
                event_queue[:] = [e for e in event_queue if not e["tag"].startswith(f"BTN_{btn_idx}")]
                keys_to_release = [k for k in synth.active_live.keys() if str(k).startswith(f"BTN_{btn_idx}")]
                for k in keys_to_release: execute_audio(k, "RELEASE", [], now)
        
    for btn_idx in just_pressed:
        if fn2_held and btn_idx == 6:
            usb_high_perf = not usb_high_perf
            if usb_high_perf:
                # Show confirmation BEFORE freezing the screen
                hw.show_screen("LIVE")
                hw.update_screen("USB", "PERF", "HEADLESS", "ACTIVE", "EXIT:", "MOD WHEEL")
                time.sleep(1) # Let user read it
            else:
                refresh_screen(now_time=now)
            continue
        
        if not in_step_mode and fn3_held and btn_idx == 6:
            if system_state != "MIXER":
                system_state = "MIXER"
                volumes = [t.get("volume", 0.8) for t in track_states] + [live_synth_vol]
                mutes = [t.get("muted", False) for t in track_states] 
                hw.update_mixer_screen(volumes, mutes, mixer_cursor)  
            continue
        if in_step_mode:
            if fn1_held and fn3_held and btn_idx == 6: 
                track_prefix = f"T{active_track}_"
                loop_events[:] = [e for e in loop_events if not str(e.get("tag", "")).startswith(track_prefix)]
                refresh_step_grid(force=True); refresh_screen("WIPED", now)
                continue
            elif fn3_held and btn_idx == 6: 
                tag_prefix = f"T{active_track}_{step_cursor}_"
                loop_events[:] = [e for e in loop_events if not str(e.get("tag", "")).startswith(tag_prefix)]
                refresh_step_grid(force=True); refresh_screen("CLEARED", now)
                continue
                
        if fn1_held and btn_idx == 6: 
            in_step_mode = not in_step_mode
            if in_step_mode: refresh_step_grid()
            refresh_screen(now_time=now)
            continue

        if fn1_held and btn_idx < 4: 
            active_track = btn_idx
            synth.current_wave_idx = track_states[active_track]["wave"]
            arp_active = False; synth.release_all(); release_all_midi()
            if in_step_mode: refresh_step_grid()
            refresh_screen(now_time=now)
            continue 

        if fn2_held and btn_idx < 4: 
            new_len = (btn_idx + 1) * 16
            track_states[active_track]["len"] = new_len
            if step_cursor >= new_len: step_cursor = new_len - 1
            beat_len = 60.0 / bpm
            q_idx = int(get_val("JAM", "Q-GRID"))
            grid_step = beat_len * [4.0, 2.0, 1.0, 0.5, 0.25][q_idx]
            max_steps = max([t["len"] for t in track_states])
            loop_length = max_steps * grid_step
            if in_step_mode: refresh_step_grid()
            refresh_screen(f"LEN: {new_len}", now)
            continue
            
        if fn3_held and btn_idx < 4: 
            track_states[btn_idx]["muted"] = not track_states[btn_idx]["muted"]
            mute_str = "MUTED" if track_states[btn_idx]["muted"] else "UNMUTED"
            refresh_screen(f"TRK {btn_idx+1} {mute_str}", now)
            keys_to_mute = [k for k in synth.active_loop.keys() if str(k).startswith(f"T{btn_idx}_")]
            for k in keys_to_mute:
                synth.release_loop(k); release_midi(k)
            continue
            
        if in_step_mode:
            local_x = step_cursor % 16
            tag = f"T{active_track}_{step_cursor}_{btn_idx}"
            exists = any(e.get("tag") == tag for e in loop_events)

            if not exists:
                hw.step_bitmap[local_x, btn_idx] = 1 
                beat_len = 60.0 / bpm
                q_idx = int(get_val("JAM", "Q-GRID"))
                multipliers = [4.0, 2.0, 1.0, 0.5, 0.25]
                grid_step = beat_len * multipliers[q_idx]
                target_time = step_cursor * grid_step
                trk_mode_idx = track_states[active_track]["mode"]
                trk_mode = modes[trk_mode_idx]
                
                if trk_mode == "DRUM":
                    loop_events.append({"time": target_time, "type": "DRUM", "tag": tag, "btn": btn_idx, "track": active_track})
                    drums = ["KICK", "SNARE", "HAT", "TOM", "RIDE", "CRASH", "CLAP"]
                    if btn_idx < len(drums): synth.play_drum(drums[btn_idx])
                else:
                    notes, _ = theory.get_chord(btn_idx, chord_joy_x, chord_joy_y, track_states[active_track]["octave"], v_lead, current_scale_string)
                    
                    # Cut the chord to a single note before dropping it into the sequence!
                    if trk_mode == "LEAD":
                        notes = [notes[0]]
                    loop_events.append({"time": target_time, "type": "PRESS", "tag": tag, "notes": notes, "track": active_track, "is_psych": (trk_mode=="PSYCH"), "is_chorus": (get_val("EFFECTS", "CHORUS")==1)})
                    loop_events.append({"time": target_time + (grid_step * 0.8), "type": "RELEASE", "tag": tag, "notes": [], "track": active_track})
                    execute_audio(f"BTN_{btn_idx}", "PRESS", notes, now, is_psych=(trk_mode=="PSYCH"))
                
                loop_events.sort(key=lambda x: x["time"])
                if looper_state in ["PLAY", "OVERDUB"]: 
                    next_event_idx = 0
                    loop_pos = (now - playback_start) % loop_length
                    while next_event_idx < len(loop_events) and loop_events[next_event_idx]["time"] <= loop_pos:
                        next_event_idx += 1
            else:
                hw.step_bitmap[local_x, btn_idx] = 0 
                loop_events[:] = [e for e in loop_events if str(e.get("tag", "")) != tag]
            continue

        active_trk_mode_idx = track_states[active_track]["mode"]
        current_trk_mode = modes[active_trk_mode_idx]
        active_trk_octave = track_states[active_track]["octave"]

        if current_trk_mode == "DRUM":
            if system_state == "PLAY" and not active_tab_data: refresh_screen("DRUMS", now)
            drums = ["KICK", "SNARE", "HAT", "TOM", "RIDE", "CRASH", "CLAP"]
            if btn_idx < len(drums): 
                live_vol = master_vol * live_synth_vol
                synth.play_drum(drums[btn_idx], vol=live_vol)
                
                if looper_state in ["RECORD", "OVERDUB"] and not in_step_mode:
                    if looper_state == "RECORD": rec_time = now - loop_start_time
                    else: rec_time = (now - playback_start) % loop_length
                    tag = f"T{active_track}_livedrum_{btn_idx}_{now}" 
                    loop_events.append({"time": rec_time, "type": "DRUM", "tag": tag, "btn": btn_idx, "track": active_track})

        elif system_state == "EARTRAINER":
            if ear_state == "GUESS":
                if btn_idx == ear_target:
                    refresh_screen("CORRECT!", now); ear_state = "SUCCESS"; ear_timer = now + 1.5
                else:
                    refresh_screen("WRONG!", now); ear_state = "PLAY_ROOT"; ear_timer = now + 1.0
        else:
            notes, chord_name = theory.get_chord(btn_idx, chord_joy_x, chord_joy_y, active_trk_octave, v_lead, current_scale_string)
            if system_state == "PLAY" and not active_tab_data: refresh_screen(chord_name, now)
            
            if current_trk_mode == "DRONE":
                keys_to_release = [k for k in synth.active_live.keys() if str(k).startswith("BTN_")]
                for k in keys_to_release: execute_audio(k, "RELEASE", [], now)
                execute_audio(f"BTN_{btn_idx}", "PRESS", notes, now)
            elif current_trk_mode in ["ONESHOT", "PSYCH", "LEAD"]:
                # If LEAD, only play the 0th index (Root Note) of the chord array
                play_notes = [notes[0]] if current_trk_mode == "LEAD" else notes
                execute_audio(f"BTN_{btn_idx}", "PRESS", play_notes, now, is_psych=(current_trk_mode == "PSYCH"))
            elif current_trk_mode == "REPEAT":
                execute_audio(f"BTN_{btn_idx}", "PRESS", notes, now)
                last_repeat_time = now
            elif current_trk_mode == "STRUM":
                event_queue[:] = [e for e in event_queue if not str(e.get("tag", "")).startswith(f"BTN_{btn_idx}")]
                for k in [k for k in synth.active_live.keys() if str(k).startswith(f"BTN_{btn_idx}")]:
                    execute_audio(k, "RELEASE", [], now)
                delay = 0.0
                for i, note in enumerate(notes):
                    event_queue.append({"time": now + delay, "tag": f"BTN_{btn_idx}_{i}", "notes": [note]})
                    delay += 0.04 
            elif current_trk_mode == "ARPEGGIO":
                next_arp_notes = notes; arp_active_btn = btn_idx; arp_grace_time = 0 
                if not arp_active:
                    arp_notes = next_arp_notes; arp_idx = 0; arp_active = True; last_arp_time = now - 1
                    
    last_buttons_state = current_set