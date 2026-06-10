from decimal import Decimal

from scisdk.scisdk import SciSDK
from unicodedata import decimal
import os
from scisdk.scisdk_defines import *
from struct import *
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque
import ctypes
import numpy as np



# ------------------ CONFIGURATION ------------------
OSCILLOSCOPE_TRIGGER_LEVEL = 5000

# Digital pulses are asociated to filter output channels of A and B (3 and 4, respectively). 
DIGITAL_CHANNEL = 3 # choose 3 for filter A, 4 for filter B

# ------------------ PLOT SETUP ------------------      
MAX_POINTS = 200
ch1_data = deque(maxlen=MAX_POINTS)
ch2_data = deque(maxlen=MAX_POINTS)

# define histogram bins (energy axis)
ENERGY_MAX = 1024      # adjust to your ADC max
NBINS = 100           # number of bins for spectrum
MIN_TIME_PLOT = 0    # min time axis for oscilloscope
MAX_TIME_PLOT = 2**10    # max time axis for oscilloscope
MIN_ADC_PLOT = -2**10       # min ADC value for analog channel plot
MAX_ADC_PLOT = 2**14    # max ADC value for analog channel plot


# Initialize SDK
sdk = SciSDK()

# Connect to device using your JSON
print("\n")

#res = sdk.AddNewDevice("usb:60166", "dt1260", "RegisterFile.json", "board0")

res = sdk.AddNewDevice("10.128.0.50:8888", "R5560", "RegisterFile.json", "board0")
if res != 0:
    print(" ! Failed to connect, code:", res)
    exit(1)
print(" - Device connected successfully!")

# -------------------------------
# ---- Load register table ----
print("\n --- Setting registers file:")

#table_file = "./PsaParameters_2us_MIRACLES_20250912.txt"
table_file = "./registers_file_test_pulse.txt"

with open(table_file, "r") as f:
    lines = f.readlines()

# Skip header
lines = lines[1:]
for line in lines:
    line = line.strip()
    if line == "":
        continue

    if len(line.split(";")) == 5:
        # remove 4th column if exists (comment)
        line = ";".join(line.split(";")[0:3] + line.split(";")[4:])

    name, reg_type, address, value = line.split(";")


    # Convert value based on type
    if reg_type == "Decimal":
        value_int = int(value)

    elif reg_type == "Hexadecimal":
        value_int = int(value, 16)

    else:
        print(f"Unknown type for {name}")
        continue

    # Extract register short name (there are 3 prefix cases : EMPTY, PCFG_ and FINE_OFS_)
    if name.startswith("PCFG_"):
        param_name = name.replace("PCFG_", "")
        path = f"board0:/MMCComponents/PCFG.{param_name}"
        #print(f"Setting {param_name} at path {path} to value {value_int}")
        err = sdk.SetParameterInteger(path, value_int)
    elif name.startswith("FINE_OFS_"):
        param_name = name.replace("FINE_OFS_", "")
        path = f"board0:/MMCComponents/FINE_OFS.{param_name}"
        #print(f"Setting {param_name} at path {path} to value {value_int}")
        err = sdk.SetParameterInteger(path, value_int)
    else:
        param_name = name
        path = f"board0:/Registers/{param_name}"
        #print(f"Setting {param_name} at path {path} to value {value_int}")
        err = sdk.SetRegister(path, value_int)


    # Set register
    if err != 0:
        #print(f"ERROR setting {param_name}, code {err}")
        continue

    # Read back to verify
    err, read_val = sdk.GetParameterInteger(path)

    if err == 0:
        print(f"{param_name:15s} set to {read_val}")
    else:
        print(f"ERROR reading back {param_name}, code {err}")
print(" - All registers loaded.")


# -------------------------------
# set oscilloscope parameters
print("\n --- Setting oscilloscope parameters:")

decimator = 1

res = sdk.SetParameterString("board0:/MMCComponents/Oscilloscope_0.data_processing","decode")
res = sdk.SetParameterInteger("board0:/MMCComponents/Oscilloscope_0.trigger_level", OSCILLOSCOPE_TRIGGER_LEVEL)
res = sdk.SetParameterString("board0:/MMCComponents/Oscilloscope_0.trigger_mode","analog")
res = sdk.SetParameterInteger("board0:/MMCComponents/Oscilloscope_0.trigger_channel", 0)
res = sdk.SetParameterInteger("board0:/MMCComponents/Oscilloscope_0.pretrigger", 150)
res = sdk.SetParameterInteger("board0:/MMCComponents/Oscilloscope_0.decimator", decimator)
res = sdk.SetParameterString("board0:/MMCComponents/Oscilloscope_0.acq_mode", "blocking")
res = sdk.SetParameterInteger("board0:/MMCComponents/Oscilloscope_0.timeout", 3000)
# allocate buffer for oscilloscope
res, buf_osc = sdk.AllocateBuffer("board0:/MMCComponents/Oscilloscope_0")
if res != 0:
    print(" ! Failed to allocate buffer for oscilloscope, code:", res)
else:
    print(" - Buffer allocated successfully for oscilloscope")

res, val = sdk.GetParameterInteger("board0:/MMCComponents/Oscilloscope_0.nanalog")
if res != 0:
    print(" ! Failed to get nanalog parameter, code:", res)
else:
    print(" - Number of analog tracks per channel:", val)

res, val = sdk.GetParameterInteger("board0:/MMCComponents/Oscilloscope_0.ndigital")
if res != 0:
    print(" ! Failed to get ndigital parameter, code:", res)
else:
    print(" - Number of digital tracks per channel:", val)

res, val = sdk.GetParameterInteger("board0:/MMCComponents/Oscilloscope_0.nchannels")
if res != 0:
    print(" ! Failed to get nchannels parameter, code:", res)
else:
    print(" - Number of channels:", val)



# ---------------- OSCILLOSCOPE FIGURE ----------------
fig, axs = plt.subplots(2, 1, figsize=(12, 12))

ax_analog  = axs[0]
ax_digital = axs[1]


ax_analog.set_ylabel("ADC (analog)")
ax_digital.set_ylabel(f"Digital tracks of CH_{DIGITAL_CHANNEL}")
ax_digital.set_xlabel("Time (samples)") 

lines_analog = [] 
for i in range(4): 
    line, = ax_analog.plot([], [], label=f"CH{i+1}") 
    lines_analog.append(line) 
ax_analog.legend() 
ax_analog.grid()

lines_digital = [] 
for i in range(4): 
    line, = ax_digital.plot([], [], label=f"D{i}") 
    lines_digital.append(line) 
ax_digital.legend()
ax_digital.grid(axis='x')



# ------------------ UPDATE FUNCTION ------------------
def update_all(frame):



    # =========================
    # OSCILLOSCOPE
    # =========================
    res_osc, buf_osc_local = sdk.ReadData("board0:/MMCComponents/Oscilloscope_0", buf_osc)

    if res_osc == 0:

        samples = buf_osc_local.info.samples_analog
        channels = buf_osc_local.info.channels

        # -------- ANALOG --------
        xar = [i * decimator for i in range(samples)]

        for ch in range(channels):
            start = ch * samples
            end = start + samples
            data = [buf_osc_local.analog[i] & 0xFFFF for i in range(start, end)]
            lines_analog[ch].set_data(xar, data)

        ax_analog.relim()
        ax_analog.autoscale_view()
        ax_analog.set_xlim(MIN_TIME_PLOT, MAX_TIME_PLOT)
        ax_analog.set_ylim(MIN_ADC_PLOT, MAX_ADC_PLOT)

        # -------- DIGITAL --------
        samples = buf_osc_local.info.samples_digital
        tracks = buf_osc_local.info.tracks_digital_per_channel

        ax_digital.set_xlim(MIN_TIME_PLOT, MAX_TIME_PLOT)
        ax_digital.set_ylim(-0.2, tracks * 1 + 0.1)

        for d in range(tracks):

            digital_wave = []

            for i in range(samples):

                index = (DIGITAL_CHANNEL - 1) * tracks * samples + d * samples + i
                raw = buf_osc_local.digital[index] & 0xFF
                bit = raw & 1
                digital_wave.append(0.5*bit + (tracks - d -1 ))

            lines_digital[d].set_data(range(samples), digital_wave)

    return (*lines_analog, *lines_digital)

# ------------------ START ANIMATION ------------------
#update_all(0)
ani = animation.FuncAnimation(fig, update_all, interval=5)
plt.show()

# -------------------------------
# Cleanup
# -------------------------------
#sdk.DetachDevice("board0")
#sdk.FreeLib()
#print("Device detached, SDK freed")