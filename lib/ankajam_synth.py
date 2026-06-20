# lib/ankajam_synth.py - Core Synth Engine for AnkaJam
import random
import synthio
import audiomixer
import audiocore
import board
import ulab.numpy as np
import audiopwmio 

class SynthEngine:
    def __init__(self, audio_out_object):
        self.audio = audio_out_object 
        
        # ---> THE 9-CHANNEL HARDWARE MIXER <---
        # Voices: 0=Live, 1=T1, 2=T2, 3=T3, 4=T4, 5=Delay, 6/7/8=Drums
        self.mixer = audiomixer.Mixer(voice_count=9, sample_rate=22050, channel_count=2, bits_per_sample=16)
        self.audio.play(self.mixer)
        
        # ---> THE FIX: INCREASE POLYPHONY TO 32 VOICES! <---
        self.synths = [synthio.Synthesizer(sample_rate=22050) for _ in range(6)]
        
        for i in range(6):
            self.mixer.voice[i].play(self.synths[i])
            self.mixer.voice[i].level = 0.8

        # ==========================================
        # ---> GLOBAL INTENSITY DICTIONARIES <---
        # ==========================================
        # 1. Synthesized Wave Intensities (Max 32767. Lower these if chords crunch/clip)
        self.synth_levels = {
            "SINE": 10000,
            "SAW": 6000,
            "SQUARE": 4000,
            "TRI": 8000,
            "STRINGS": 6000,
            "FM_EPIANO": 12000,
            "FM_HX7": 10000,
            "FM_BELL": 14000,
            "FM_ORGAN": 10000,
            "FM_BRASS": 9000
        }
        
        # 2. Custom WAV Patch Intensities (0.0 to 1.0 multiplier)
        # Add your custom file names here (without .wav). If not listed, it defaults to 0.6 (60%)
        self.patch_levels = {
            "DEFAULT": 0.6,
            "MYBASS": 0.8,
            "PADSOUND": 0.4
        }
        # ==========================================
            
        self.wave_names = ["SINE", "SAW", "SQUARE", "TRI", "STRINGS", "FM_EPIANO", "FM_HX7", "FM_BELL", "FM_ORGAN", "FM_BRASS"]
        self.waveforms = []
        self._generate_waveforms()
        self._load_user_patches() 
        self.current_wave_idx = 1
        
        self.env = synthio.Envelope(attack_time=0.05, decay_time=0.1, sustain_level=0.7, release_time=0.8)
        self.psych_lfo = synthio.LFO(rate=1.0, scale=1000, offset=2600)
        self.psych_filter = synthio.Biquad(synthio.FilterMode.LOW_PASS, frequency=self.psych_lfo, Q=1.5)
        
        self.active_live = {}
        self.active_loop = {}
        self.active_delay = {}
        
        self.glide_targets = {} 
        self.last_frequencies = [] 
        self.next_drum_voice = 6 

    def _generate_fm_wave(self, ratio, index, scale):
            t = np.linspace(0, 2 * np.pi, 512, endpoint=False)
            fm_wave = np.sin(t + index * np.sin(ratio * t))
            return np.array(fm_wave * scale, dtype=np.int16)

    def _generate_waveforms(self):
        sz = 512
        sine = np.sin(np.linspace(0, 2*np.pi, sz, endpoint=False))
        self.waveforms.append(np.array(sine * self.synth_levels["SINE"], dtype=np.int16))
        
        saw = np.zeros(sz)
        for h in range(1, 10): saw += (1/h) * np.sin(np.linspace(0, 2*np.pi*h, sz, endpoint=False))
        self.waveforms.append(np.array(saw * self.synth_levels["SAW"], dtype=np.int16)) 
        
        sq = np.zeros(sz)
        for h in range(1, 10, 2): sq += (1/h) * np.sin(np.linspace(0, 2*np.pi*h, sz, endpoint=False))
        self.waveforms.append(np.array(sq * self.synth_levels["SQUARE"], dtype=np.int16))

        tri = np.zeros(sz)
        for h in range(1, 10, 2): tri += ((-1)**((h-1)/2)/(h**2)) * np.sin(np.linspace(0, 2*np.pi*h, sz, endpoint=False))
        self.waveforms.append(np.array(tri * self.synth_levels["TRI"], dtype=np.int16))

        self.waveforms.append(self.waveforms[1]) # STRINGS (Copy of Saw for now)

        self.waveforms.append(self._generate_fm_wave(ratio=2, index=1.5, scale=self.synth_levels["FM_EPIANO"]))
        self.waveforms.append(self._generate_fm_wave(ratio=1, index=2.5, scale=self.synth_levels["FM_HX7"])) 
        self.waveforms.append(self._generate_fm_wave(ratio=7, index=2.0, scale=self.synth_levels["FM_BELL"])) 
        self.waveforms.append(self._generate_fm_wave(ratio=3, index=1.2, scale=self.synth_levels["FM_ORGAN"])) 
        self.waveforms.append(self._generate_fm_wave(ratio=1, index=3.0, scale=self.synth_levels["FM_BRASS"]))  

    def _load_user_patches(self):
        try:
            import os
            if "patches" not in os.listdir("/"): os.mkdir("/patches")
            for file in os.listdir("/patches"):
                if file.endswith(".wav"):
                    try:
                        with open("/patches/" + file, "rb") as f:
                            f.seek(44)
                            data = f.read()
                            wave_array = np.frombuffer(data, dtype=np.int16)
                            self.waveforms.append(wave_array)
                            self.wave_names.append(file.replace(".wav", "").upper()[:8])
                    except Exception as e: 
                        print(f"WAV Error ({file}):", e)
        except Exception as e: 
            print("Filesystem Error:", e)

    def change_waveform(self, delta):
        self.current_wave_idx = (self.current_wave_idx + delta) % len(self.waveforms)
        return self.wave_names[self.current_wave_idx]

    def set_live_volume(self, val):
        pass # Now handled dynamically per-note!
        
    def set_loop_volume(self, val):
        pass 

    def set_adsr(self, a, d, s, r):
        self.env = synthio.Envelope(attack_time=a, decay_time=d, sustain_level=s, release_time=r)

    # Helper to instantly route tags to the correct mixer fader
    def _get_target_idx(self, tag):
        tag_str = str(tag)
        if tag_str.startswith("T0_") or tag_str.startswith("L0_"): return 1
        if tag_str.startswith("T1_") or tag_str.startswith("L1_"): return 2
        if tag_str.startswith("T2_") or tag_str.startswith("L2_"): return 3
        if tag_str.startswith("T3_") or tag_str.startswith("L3_"): return 4
        return 0 # Default to LIVE fader

    def trigger_live(self, tag, midi_notes, is_psych=False, is_chorus=False, glide_time=0.0, vel_min=1.0, vol=1.0, wave_idx=None, explicit_vel=None, midi_vel_min=0):
        if wave_idx is None: wave_idx = self.current_wave_idx
        
        target_idx = self._get_target_idx(tag)
        self.mixer.voice[target_idx].level = max(0.0, min(1.0, vol))
        target_synth = self.synths[target_idx]
        
        wave_name = self.wave_names[wave_idx]
        patch_vol = self.patch_levels.get(wave_name, self.patch_levels["DEFAULT"]) if wave_idx >= 10 else 1.0
        
        flt = self.psych_filter if is_psych else None
        target_hz = [synthio.midi_to_hz(m) for m in midi_notes]
        
        if not hasattr(self, 'last_frequencies'): self.last_frequencies = []
            
        if glide_time > 0 and tag in self.active_live:
            existing = self.active_live[tag]["notes"]
            for i in range(min(len(target_hz), len(existing))):
                self.glide_targets[existing[i]] = target_hz[i]
            
            if len(target_hz) > len(existing):
                new_n = []
                for hz in target_hz[len(existing):]:
                    # ---> FIX: Use exact MIDI velocity if available! <---
                    if explicit_vel is not None: final_amp = explicit_vel * patch_vol
                    else: final_amp = random.uniform(vel_min, 1.0) * patch_vol
                    n = synthio.Note(frequency=hz, waveform=self.waveforms[wave_idx], envelope=self.env, filter=flt, amplitude=final_amp)
                    self.glide_targets[n] = hz
                    new_n.append(n)
                target_synth.press(new_n)
                existing.extend(new_n)
            elif len(existing) > len(target_hz):
                to_rel = existing[len(target_hz):]
                target_synth.release(to_rel)
                for n in to_rel: self.glide_targets.pop(n, None)
                self.active_live[tag]["notes"] = existing[:len(target_hz)]
            self.last_frequencies = target_hz 
        else:
            self.release_live(tag)
            notes = []
            for i, hz in enumerate(target_hz):
                start_hz = self.last_frequencies[i] if (glide_time > 0 and i < len(self.last_frequencies)) else hz
                
                # ---> FIX: Use exact MIDI velocity if available! <---
                if explicit_vel is not None:
                    final_amplitude = explicit_vel * patch_vol
                else:
                    final_amplitude = random.uniform(vel_min, 1.0) * patch_vol
                    
                n = synthio.Note(frequency=start_hz, waveform=self.waveforms[wave_idx], envelope=self.env, filter=flt, amplitude=final_amplitude)
                self.glide_targets[n] = hz
                notes.append(n)
                
                if is_chorus:
                    nc = synthio.Note(frequency=start_hz*1.006, waveform=self.waveforms[wave_idx], envelope=self.env, filter=flt, amplitude=final_amplitude*0.6)
                    self.glide_targets[nc] = hz * 1.006
                    notes.append(nc)
                    
            target_synth.press(notes)
            self.active_live[tag] = {"notes": notes, "idx": target_idx}
            self.last_frequencies = target_hz

    def release_live(self, tag):
        if tag in self.active_live:
            data = self.active_live[tag]
            self.synths[data["idx"]].release(data["notes"]) 
            for n in data["notes"]:
                if n in self.glide_targets: del self.glide_targets[n]
            del self.active_live[tag]

    def trigger_loop(self, tag, midi_notes, is_psych=False, is_chorus=False, vol=1.0, wave_idx=None):
        if wave_idx is None: wave_idx = self.current_wave_idx
        self.release_loop(tag)
        
        target_idx = self._get_target_idx(tag)
        self.mixer.voice[target_idx].level = max(0.0, min(1.0, vol))
        
        wave_name = self.wave_names[wave_idx]
        patch_vol = self.patch_levels.get(wave_name, self.patch_levels["DEFAULT"]) if wave_idx >= 10 else 1.0
        
        flt = self.psych_filter if is_psych else None
        notes = []
        for hz in [synthio.midi_to_hz(m) for m in midi_notes]:
            notes.append(synthio.Note(frequency=hz, waveform=self.waveforms[wave_idx], envelope=self.env, filter=flt, amplitude=patch_vol))
            if is_chorus: notes.append(synthio.Note(frequency=hz*1.006, waveform=self.waveforms[wave_idx], envelope=self.env, filter=flt, amplitude=0.6*patch_vol))
        self.synths[target_idx].press(notes)
        self.active_loop[tag] = {"notes": notes, "idx": target_idx}

    def release_loop(self, tag):
        if tag in self.active_loop:
            data = self.active_loop[tag]
            self.synths[data["idx"]].release(data["notes"])
            del self.active_loop[tag]

    def trigger_delay(self, tag, midi_notes, is_psych=False, is_chorus=False, vol=1.0, wave_idx=None):
        if wave_idx is None: wave_idx = self.current_wave_idx
        self.release_delay(tag)
        self.mixer.voice[5].level = max(0.0, min(1.0, vol * 0.4)) 
        
        wave_name = self.wave_names[wave_idx]
        patch_vol = self.patch_levels.get(wave_name, self.patch_levels["DEFAULT"]) if wave_idx >= 10 else 1.0
        
        flt = self.psych_filter if is_psych else None
        notes = []
        for hz in [synthio.midi_to_hz(m) for m in midi_notes]:
            notes.append(synthio.Note(frequency=hz, waveform=self.waveforms[wave_idx], envelope=self.env, filter=flt, amplitude=patch_vol))
            if is_chorus: notes.append(synthio.Note(frequency=hz*1.006, waveform=self.waveforms[wave_idx], envelope=self.env, filter=flt, amplitude=0.6*patch_vol))
        self.synths[5].press(notes)
        self.active_delay[tag] = notes

    def release_delay(self, tag):
        if tag in self.active_delay: 
            self.synths[5].release(self.active_delay[tag])
            del self.active_delay[tag]

    def release_all(self):
        for s in self.synths: s.release_all()
        self.active_live.clear(); self.active_loop.clear(); self.active_delay.clear()
        self.glide_targets.clear()

    def play_drum(self, drum_type, vol=1.0):
        try:
            file_map = {"KICK": "samples/kick.wav", "SNARE": "samples/snare.wav", "HAT": "samples/hat.wav", "TOM": "samples/tom.wav", "RIDE": "samples/ride.wav", "CRASH": "samples/crash.wav", "CLAP": "samples/clap.wav"}
            if drum_type in file_map:
                self.mixer.voice[self.next_drum_voice].level = max(0.0, min(1.0, vol))
                wave = audiocore.WaveFile(open(file_map[drum_type], "rb"))
                self.mixer.voice[self.next_drum_voice].play(wave)
                self.next_drum_voice += 1
                if self.next_drum_voice > 8: self.next_drum_voice = 6
        except OSError: pass

    def update_tremolo(self, is_on):        
        if not hasattr(self, 'trem_lfo'): self.trem_lfo = synthio.LFO(rate=5.0, scale=0.0, offset=1.0)
        if is_on:
            self.trem_lfo.scale = 0.5   
            self.trem_lfo.offset = 0.5  
        else:
            self.trem_lfo.scale = 0.0   
            self.trem_lfo.offset = 1.0  
            
        for tag, data in self.active_live.items():
            for note in data["notes"]:
                if getattr(note, 'amplitude', None) != self.trem_lfo: note.amplitude = self.trem_lfo
        for tag, data in self.active_loop.items():
            for note in data["notes"]:
                if getattr(note, 'amplitude', None) != self.trem_lfo: note.amplitude = self.trem_lfo