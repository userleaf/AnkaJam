@echo off
echo Processing raw waveforms for Anka-Jam...
echo Applying Mono, 22.05kHz, 16-bit PCM, and -18 LUFS Normalization...

for %%f in (raw\*.wav) do (
    ffmpeg -y -i "%%f" -af "loudnorm=I=-18:LRA=11:TP=-1.5" -ac 1 -ar 22050 -c:a pcm_s16le -map_metadata -1 "%%~nxf"
)

echo Cleaning up raw folder...
del /Q "raw\*.wav"

echo All done! Ready to copy to the Pico.
pause