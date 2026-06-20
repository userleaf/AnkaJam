# 🎹 Anka-Jam: The CircuitPython Groovebox

Anka-Jam is a portable, standalone hardware synthesizer, 4-track step sequencer, and groovebox powered by the **Raspberry Pi Pico 2 (RP2350)** and CircuitPython's `synthio` library. 

Designed for tactile live performance, it features a built-in music theory engine, physical pitch-bending via a built-in gyroscope, external USB MIDI keyboard hosting, and a robust 4-track audio engine with independent volume control.

---

## ✨ Key Features

* **Advanced Audio Engine:** Powered by `synthio`. Features custom ADSR envelopes, LFOs, Delay, Chorus, Tremolo, and Portamento (Glide).
* **4-Track Step Sequencer & Looper:** Record live loops or program steps on a 16-to-64 step grid across 4 independent tracks. Includes a dedicated Drum engine.
* **Master Mixer & Volume Controls:** Built-in digital mixer screen to adjust the volume levels and mute states of each of your 4 sequencer tracks and your live performance track independently.
* **Music Theory Engine:** 7 physical piano-key buttons mapped intelligently to musical scales and chords. Use the analog joystick to dynamically voice chords, change inversions, and add extensions.
* **Physical Pitch Bending:** Built-in MPU-6500 accelerometer allows you to physically tilt the device in `LEAD` mode for expressive, guitar-style whammy bar pitch bends (+/- 2 semitones).
* **8 Performance Modes:** Oneshot, Strum, Arpeggio, Psych, Drum, Drone, Repeat, and Lead.
* **USB Host Support:** Plug in a class-compliant USB MIDI keyboard to play Anka-Jam headless or as an external sound module.
* **Mini-Games:** Includes "Hero-Jam" (a falling-note rhythm game based on tab files) and a built-in Ear Trainer.

---

## 🛠️ Hardware Requirements

To build Anka-Jam, you will need:
* **Microcontroller:** Raspberry Pi Pico 2 (RP2350)
* **Audio:** MAX98357A I2S Class-D Amplifier Breakout + 3W Speaker
* **Display:** 128x64 OLED Display (SSD1306 via I2C)
* **Sensor:** MPU-6500 / MPU-6050 Accelerometer Breakout (I2C)
* **Inputs:** * 7x Mechanical/Arcade Buttons (Note Keys)
    * 3x Mechanical Buttons (Function Keys)
    * 1x Analog Joystick with Z-Axis click
* **Power:** TP4056 Charge Controller, 18650 Li-ion Battery, and an SPDT/SPST Slide Switch for main power.
* **Connectivity:** USB-C Breakout for power/charging, USB-A female breakout for MIDI Hosting.

### 🔌 Complete Wiring Map (Pinout & Power)

Anka-Jam uses a highly optimized physical wiring cluster for easy header soldering.

**1. Power Routing:**
* **Battery:** Connect the 3.7V Li-ion battery to the **B+** and **B-** pads of the TP4056.
* **Main Switch:** Connect the TP4056 **OUT+** pad to the middle pin of your Power Switch. Connect one of the outer pins of the switch to the Pico's **VSYS** (Pin 39).
* **Ground:** Connect the TP4056 **OUT-** pad to any Pico **GND** pin.
* *(Note: Do NOT power the Pico directly from the battery without the switch, or it will never turn off!)*

**2. Data & Peripherals:**
| Component | Function | Pico Pin |
| :--- | :--- | :--- |
| **I2S Audio Amp** | BCLK, LRCLK, DIN | GP2, GP3, GP4 |
| **Amp Power** | VIN, GND | VSYS, GND |
| **I2C Bus (OLED & MPU)** | SDA, SCL | GP20, GP21 |
| **I2C Power** | VCC, GND | 3V3(OUT) Pin 36, GND |
| **USB MIDI Host** | D+, D-, VBUS | GP16, GP17, VBUS |
| **Note Buttons 1-7** | Digital In (Pull-Up) | GP9, GP6, GP10, GP7, GP11, GP8, GP12 |
| **Fn Buttons 1-3** | Digital In (Pull-Up) | GP18, GP19, GP22 |
| **Analog Joystick** | X-Axis, Y-Axis | GP26 (ADC0), GP27 (ADC1) |
| **Joystick Click** | Digital In (Pull-Up) | GP13 |
*(Note: Wire the other side of all buttons and the joystick directly to a common Ground).*

---

## 💻 Software Installation

1. Install **CircuitPython 10.x** on your Raspberry Pi Pico 2.
2. Copy the following required libraries from the Adafruit CircuitPython Bundle to your `lib` folder:
   * `adafruit_display_text`
   * `adafruit_displayio_ssd1306`
   * `adafruit_midi`
   * `adafruit_usb_host_midi`
   * `adafruit_bus_device`
3. Copy the Anka-Jam project files to the root of the Pico drive:
   * `code.py` (Main firmware)
   * `/lib/ankajam_hardware.py` (Hardware definitions & UI)
   * `/lib/ankajam_theory.py` (Music theory & chord math)
   * `/lib/ankajam_synth.py` (Audio generation)
   * `/tabs/` (Folder containing `.json` song files for Hero-Jam)

### 🧠 The MPU-6500 Bypass Hack
*Note for developers:* Anka-Jam does not use standard Adafruit libraries for the accelerometer. Because the market is flooded with counterfeit MPU-6050s (which are actually MPU-6500s with different ID registers), Anka-Jam uses a custom, bare-metal `struct`-based I2C driver wrapped in `I2CDevice` to ensure 30FPS hardware tilt-reading without locking up the OLED display bus.

---

## 🕹️ Controls Cheat Sheet

### Core Navigation
* **Open Main Menu:** Hold `Joy Click` (> 0.6s). *(Tap Joy Click to select, move Joy Y to scroll).*
* **Save Configuration:** Hold `Fn1` + Tap `Joy Click`.
* **PANIC (Kill all sound):** Hold `Fn1` + `Fn2` + `Fn3` simultaneously.

### The 4-Track Sequencer & Looper
Anka-Jam features a powerful looper that can record your live playing or be programmed step-by-step.
* **Select Active Track:** Hold `Fn1` + Press Note 1, 2, 3, or 4.
* **Toggle Step Sequencer UI:** Hold `Fn1` + Press `Note 7`.
* **Change Track Length:** Hold `Fn2` + Press Note 1, 2, 3, or 4 (Sets track to 16, 32, 48, or 64 steps).
* **Transport Control (Play/Rec/Overdub):** Tap `Joy Click`.
* **Hard Stop / Clear Active Loop:** Hold `Fn3` + Tap `Joy Click`.
* **Wipe Entire Track (In Step Mode):** Hold `Fn1` + `Fn3` + Press `Note 7`.

### Volume & Master Mixer
* **Open Master Mixer:** Hold `Fn3` + Press `Note 7`. *(Provides a visual UI for 4 tracks + Live).*
* **Mute/Unmute Quick-Select:** Hold `Fn3` + Press Note 1, 2, 3, or 4.

### Track & Sound Shaping
*Hold a Function key and move the joystick to shape your sound:*
* **Fn1 + Joy Up/Down:** Change Key.
* **Fn1 + Joy Left/Right:** Change Mode (Strum, Arp, Drum, Lead, etc.).
* **Fn2 + Joy Up/Down:** Change Octave.
* **Fn2 + Joy Left/Right:** Change Waveform.
* **Fn3 + Joy Up/Down:** Change Scale.
* **Fn3 + Joy Left/Right:** Change BPM.

---

## 📄 License
This project is open-source. Feel free to fork, mod, and build your own hardware enclosures!
