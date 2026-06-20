# ankajam_theory.py - Music Theory and Chord Generation for AnkaJam
class MusicTheory:
    def __init__(self):
        self.keys = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        self.current_key_idx = 0 
        self.last_chord_notes = [] 
        self.joystick_mode = 0 # 0=DEFAULT, 1=EXTENDED, 2=CHROMATIC
        
        self.scales = {
            "MAJOR":    {"int": [0, 2, 4, 5, 7, 9, 11], "qual": [0, 1, 1, 0, 0, 1, 2]},
            "NAT MIN":  {"int": [0, 2, 3, 5, 7, 8, 10], "qual": [1, 2, 0, 1, 1, 0, 0]},
            "HARM MIN": {"int": [0, 2, 3, 5, 7, 8, 11], "qual": [1, 2, 3, 1, 0, 0, 2]},
            "MEL MIN":  {"int": [0, 2, 3, 5, 7, 9, 11], "qual": [1, 1, 3, 0, 0, 2, 2]},
            "MAJ PENT": {"int": [0, 2, 4, 7, 9],        "qual": [0, 1, 1, 0, 1]},
            "MIN PENT": {"int": [0, 3, 5, 7, 10],       "qual": [1, 0, 1, 1, 0]},
            "BLUES":    {"int": [0, 3, 5, 6, 7, 10],    "qual": [1, 0, 1, 2, 1, 0]},
            "DORIAN":   {"int": [0, 2, 3, 5, 7, 9, 10], "qual": [1, 1, 0, 0, 1, 2, 0]},
            "MIXOLYD":  {"int": [0, 2, 4, 5, 7, 9, 10], "qual": [0, 1, 2, 0, 1, 1, 0]},
            "LYDIAN":   {"int": [0, 2, 4, 6, 7, 9, 11], "qual": [0, 0, 1, 2, 0, 1, 1]}
        }

    def get_key_name(self): return self.keys[self.current_key_idx]
    def set_key(self, delta): self.current_key_idx = (self.current_key_idx + delta) % 12

    def get_chord(self, button_index, joystick_x, joystick_y, octave=0, voice_lead=False, scale_name="MAJOR"):
        root_midi = 60 + self.current_key_idx + (octave * 12)
        
        scale_data = self.scales.get(scale_name, self.scales["MAJOR"])
        scale_intervals = scale_data["int"]; scale_qualities = scale_data["qual"]
        scale_length = len(scale_intervals)
        
        mapped_degree = button_index % scale_length
        wrap_octave = button_index // scale_length
        
        base_root_offset = scale_intervals[mapped_degree]
        root_note = root_midi + base_root_offset + (wrap_octave * 12)
        quality = scale_qualities[mapped_degree]
        
        if quality == 0: chord_intervals = [0, 4, 7]     # Major
        elif quality == 1: chord_intervals = [0, 3, 7]   # Minor
        elif quality == 2: chord_intervals = [0, 3, 6]   # Diminished
        elif quality == 3: chord_intervals = [0, 4, 8]   # Augmented
        else: chord_intervals = [0, 4, 7]

        is_major = (chord_intervals[1] == 4)

        x_dir, y_dir = 0, 0
        if joystick_x < -0.6: x_dir = -1   
        elif joystick_x > 0.6: x_dir = 1   
        if joystick_y < -0.6: y_dir = -1   
        elif joystick_y > 0.6: y_dir = 1   

        # ---> THE NEW 3-TIER JOYSTICK MAP <---
        if self.joystick_mode == 0: # DEFAULT MODE
            if y_dir == -1 and x_dir == 0: chord_intervals[1] = 3 if is_major else 4
            elif y_dir == 1 and x_dir == 0: chord_intervals[1] = 5
            elif y_dir == 0 and x_dir == -1: chord_intervals[1] = 3; chord_intervals[2] = 6
            elif y_dir == 0 and x_dir == 1: chord_intervals.append(11 if is_major else 10)
            elif y_dir == -1 and x_dir == -1: chord_intervals[1] = 4; chord_intervals[2] = 8
            elif y_dir == -1 and x_dir == 1: chord_intervals[1] = 4; chord_intervals[2] = 7; chord_intervals.append(10)
            elif y_dir == 1 and x_dir == -1: chord_intervals[1] = 2  
            elif y_dir == 1 and x_dir == 1: chord_intervals.append(14)
            
        elif self.joystick_mode == 1: # EXTENDED MODE
            if y_dir == -1 and x_dir == 0: chord_intervals[1] = 3 if is_major else 4
            elif y_dir == 1 and x_dir == 0: chord_intervals = [0, 4, 7, 10, 15] # dom7#9 (Hendrix Chord)
            elif y_dir == 0 and x_dir == -1: chord_intervals = [0, 5, 7, 10]    # sus4+7
            elif y_dir == 0 and x_dir == 1: chord_intervals.append(17)          # add11
            elif y_dir == -1 and x_dir == -1: chord_intervals = [0, 3, 6, 10]   # half-dim7 (m7b5)
            elif y_dir == -1 and x_dir == 1: chord_intervals = [0, 4, 7, 10, 14]# dom9
            elif y_dir == 1 and x_dir == -1: chord_intervals = [0, 4, 7, 14]    # add9
            elif y_dir == 1 and x_dir == 1: chord_intervals = [0, 3, 7, 10, 17] # min11
            
        elif self.joystick_mode == 2: # CHROMATIC (JAZZ) MODE
            if y_dir == -1 and x_dir == 0: chord_intervals = [0, 3, 7, 11]      # min(maj7)
            elif y_dir == 1 and x_dir == 0: chord_intervals = [0, 4, 7, 11, 21] # Maj13
            elif y_dir == 0 and x_dir == -1: chord_intervals = [0, 3, 6, 10]    # half-dim7
            elif y_dir == 0 and x_dir == 1: chord_intervals = [0, 4, 7, 9, 14]  # 6/9
            elif y_dir == -1 and x_dir == -1: chord_intervals = [0, 4, 7, 11, 18]# Maj7#11 (Lydian Chord)
            elif y_dir == -1 and x_dir == 1: chord_intervals = [0, 4, 7, 10, 21]# dom13
            elif y_dir == 1 and x_dir == -1: chord_intervals = [0, 4, 7, 10, 13]# dom7b9
            elif y_dir == 1 and x_dir == 1: chord_intervals = [0, 4, 8, 10, 15] # dom7alt (#5#9)

        final_notes = [root_note + i for i in chord_intervals]
        
        # SMART VOICE LEADING MATH
        if voice_lead and self.last_chord_notes:
            last_center = sum(self.last_chord_notes) / len(self.last_chord_notes)
            inv0 = final_notes
            inv1 = [final_notes[1], final_notes[2], final_notes[0] + 12] + [n+12 for n in final_notes[3:]] if len(final_notes) > 2 else final_notes
            inv2 = [final_notes[2], final_notes[0] + 12, final_notes[1] + 12] + [n+12 for n in final_notes[3:]] if len(final_notes) > 2 else final_notes
            
            centers = [sum(inv)/len(inv) for inv in [inv0, inv1, inv2]]
            best_idx, min_dist = 0, 999; best_shift = 0
            
            for i, c in enumerate(centers):
                octave_shift = round((last_center - c) / 12) * 12
                dist = abs((c + octave_shift) - last_center)
                if dist < min_dist:
                    min_dist, best_idx, best_shift = dist, i, octave_shift
                    
            best_inv = [inv0, inv1, inv2][best_idx]
            final_notes = [n + best_shift for n in best_inv]

            avg_pitch = sum(final_notes) / len(final_notes)
            lower_bound = 54 + (octave * 12)
            upper_bound = 72 + (octave * 12)
            
            if avg_pitch < lower_bound: final_notes = [n + 12 for n in final_notes]
            elif avg_pitch > upper_bound: final_notes = [n - 12 for n in final_notes]
                
        self.last_chord_notes = final_notes
        
        # SCREEN FORMATTER (Updated for jazz extensions!)
        note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        root_name = note_names[root_note % 12]
        
        if chord_intervals == [0, 4, 7, 10, 15]: chord_name = f"{root_name} 7#9"
        elif chord_intervals == [0, 5, 7, 10]: chord_name = f"{root_name} sus4(7)"
        elif chord_intervals == [0, 3, 6, 10]: chord_name = f"{root_name} m7b5"
        elif chord_intervals == [0, 4, 7, 10, 14]: chord_name = f"{root_name} 9"
        elif chord_intervals == [0, 3, 7, 11]: chord_name = f"{root_name} m(M7)"
        elif chord_intervals == [0, 4, 7, 11, 21]: chord_name = f"{root_name} M13"
        elif chord_intervals == [0, 4, 7, 9, 14]: chord_name = f"{root_name} 6/9"
        elif chord_intervals == [0, 4, 7, 11, 18]: chord_name = f"{root_name} M7#11"
        elif chord_intervals == [0, 4, 7, 10, 21]: chord_name = f"{root_name} 13"
        elif chord_intervals == [0, 4, 7, 10, 13]: chord_name = f"{root_name} 7b9"
        elif chord_intervals == [0, 4, 8, 10, 15]: chord_name = f"{root_name} 7alt"
        else:
            qual_name = ""
            if 4 in chord_intervals and 8 in chord_intervals: qual_name = "Aug"
            elif 3 in chord_intervals and 6 in chord_intervals: qual_name = "Dim"
            elif 5 in chord_intervals and 7 in chord_intervals: qual_name = "Sus4"
            elif 2 in chord_intervals and 7 in chord_intervals: qual_name = "Sus2"
            elif 4 in chord_intervals and 7 in chord_intervals: qual_name = "Maj"
            elif 3 in chord_intervals and 7 in chord_intervals: qual_name = "Min"
            
            ext_name = ""
            if 10 in chord_intervals:
                if qual_name == "Maj": qual_name = ""; ext_name = "7"
                else: ext_name = "7" 
            elif 11 in chord_intervals:
                if qual_name == "Maj": qual_name = "" 
                ext_name = "Maj7"
                
            if 14 in chord_intervals:
                if ext_name == "7": ext_name = "9" 
                elif ext_name == "Maj7": ext_name = "Maj9"
                else: ext_name = "(add9)"
                if qual_name == "Maj": qual_name = "" 
            elif 17 in chord_intervals:
                if ext_name == "7": ext_name = "11"
                elif ext_name == "Maj7": ext_name = "Maj11"
                elif qual_name == "Min": ext_name = "11"; qual_name = "m"
                else: ext_name = "(add11)"
                if qual_name == "Maj": qual_name = ""
            
            chord_name = f"{root_name} {qual_name}{ext_name}".strip()
            
        return final_notes, chord_name