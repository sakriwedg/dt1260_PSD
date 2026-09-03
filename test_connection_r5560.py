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
import time


# ------------------ CONFIGURATION ------------------
#OSCILLOSCOPE_TRIGGER_LEVEL = 5000
OSCILLOSCOPE_TRIGGER_LEVEL = 10000

# Digital pulses are asociated to filter output channels of A and B (2 and 3, respectively). 
DIGITAL_CHANNEL = 2 # choose 2 for filter A, 3 for filter B

TRIGGER_CHANNEL = 0 # choose 0 for channel A, 1 for channel B

PRETRIGGER_SAMPLES = 150

TRIGGER_MODE = "analog" # 
NUMBER_OF_RECORDS = 100

OSCILLOSCOPE_ID = 1
CUSTOM_PACKET = "CP_ETHERNET"
# ------------------ PLOT SETUP ------------------      
MAX_POINTS = 200
ch1_data = deque(maxlen=MAX_POINTS)
ch2_data = deque(maxlen=MAX_POINTS)

# Define what channels to plot 

CHANNELS_TO_PLOT = [0,1,2,3] # list of channels to plot (0-3)


# define histogram bins (energy axis)
MIN_TIME_PLOT = 0    # min time axis for oscilloscope
MAX_TIME_PLOT = 2**10    # max time axis for oscilloscope
MIN_ADC_PLOT = -2**10       # min ADC value for analog channel plot
MAX_ADC_PLOT = 2**18    # max ADC value for analog channel plot

MIN_ADC_PLOT = -2**10       # min ADC value for analog channel plot
MAX_ADC_PLOT = 2**14 
clock = 1.25e8
# Initialize SDK
sdk = SciSDK()

# Connect to device using your JSON
print("\n")

res = sdk.AddNewDevice("10.128.0.50:8888", "R5560", "RegisterFile_v1.json", "board0")
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
        err = sdk.SetParameterInteger(path, value_int)
        
        # Read back to verify
        err, read_val = sdk.GetParameterInteger(path)
        if err == 0:
            print(f"{param_name:15s} set to {read_val}")
        else:
            print(f"ERROR reading back {param_name}, code {err}")

    elif name.startswith("FINE_OFS_"):
        param_name = name.replace("FINE_OFS_", "")
        path = f"board0:/MMCComponents/FINE_OFS.{param_name}"
        err = sdk.SetParameterInteger(path, value_int)

    else:
        param_name = name
        path = f"board0:/Registers/{param_name}"
        err = sdk.SetRegister(path, value_int)
        err, read_val = sdk.GetRegister(path)


    # Set register
    if err != 0:
        #print(f"ERROR setting {param_name}, code {err}")
        continue




print(" - All registers loaded.")



print(f" --- {CUSTOM_PACKET} debugging ---")


sdk.SetParameterString(f"board0:/MMCComponents/{CUSTOM_PACKET}.thread","false")
sdk.SetParameterString(f"board0:/MMCComponents/{CUSTOM_PACKET}.acq_mode","non-blocking")

res, v = sdk.GetParameterString(f"board0:/MMCComponents/{CUSTOM_PACKET}.acq_mode")
print("acq_mode =", v)


# Allocate CP buffer
print("\n --- Allocating CP buffer:")
res, buf_cus = sdk.AllocateBuffer(f"board0:/MMCComponents/{CUSTOM_PACKET}", 1024)
if res != 0:
    print("Failed to allocate CP buffer")
    exit(1)
else:
    print(" - CP buffer allocated successfully")

# Start CP
res = sdk.ExecuteCommand(f"board0:/MMCComponents/{CUSTOM_PACKET}.start", "")
if res != 0:
    print("Failed to start CP")
    exit(1)
else:
    print(" - CP started successfully")
time.sleep(2)

# Plotting histogram of side A and side B

# histogram bins
n_bins = 100
max_bin = 2**16
bins = np.arange(0, max_bin + 1, max_bin // n_bins)
hist_side_A = np.zeros(len(bins) - 1)
hist_side_B = np.zeros(len(bins) - 1)

# scatter plot A vs B
scatter_A = []
scatter_B = []

# channel histogram
bins_channel = np.arange(0, 32, 1)
hist_channel = np.zeros(len(bins_channel) - 1)

word0_list = []
word1_list = []
global_time = []


for n in range(NUMBER_OF_RECORDS):

    # print progress every 100 events and flush output
    if n % 100 == 0:
        print(f"Reading event {n}/{NUMBER_OF_RECORDS}", end="\r", flush=True)

    res_cus, buf = sdk.ReadData(f"board0:/MMCComponents/{CUSTOM_PACKET}", buf_cus)

    if res_cus != 0:
        print("Read error:", res_cus)
        continue

    valid = int(buf.info.valid_data)

    if valid <= 0:
        continue

    DEBUG_EVERY   = 100   # change to 100 or 1000
    PRINT_FIRST_N = 0     # always print first few events


    for evt in range(valid):

        def swap32(x):
            return ((x & 0xFF) << 24) | \
                ((x & 0xFF00) << 8) | \
                ((x & 0xFF0000) >> 8) | \
                ((x >> 24) & 0xFF)

        w0 = swap32(buf.data[evt].row[0])
        w1 = swap32(buf.data[evt].row[1])
        w2 = swap32(buf.data[evt].row[2])
        w3 = swap32(buf.data[evt].row[3])

        timestamp = (w1 << 32) | w0
        channel   = (w2 >> 8) & 0xFF
        energy_A  = w3 & 0xFFFF
        energy_B  = (w3 >> 16) & 0xFFFF


        if evt < PRINT_FIRST_N:
           print(f"Event {evt}: w0={w0:#010x}, w1={w1:#010x}, w2={w2:#010x}, w3={w3:#010x}")


        # ---------------------------
        # Plotting structures
        # ---------------------------
        hist_side_A += np.histogram(energy_A, bins=bins)[0]
        hist_side_B += np.histogram(energy_B, bins=bins)[0]
        scatter_A.append(energy_A)
        scatter_B.append(energy_B)
        global_time.append(timestamp)
        list_channel = [channel]
        hist_channel += np.histogram(list_channel, bins=bins_channel)[0]    


        if evt % DEBUG_EVERY == 0:  
            word0_list.append(w0)
            word1_list.append(w1)


if NUMBER_OF_RECORDS > 0:

    # plot w0
    plt.figure(figsize=(10, 6))
    plt.plot(word0_list, marker='o', linestyle='-', markersize=3)
    plt.xlabel("Event")
    plt.ylabel("w0")
    plt.grid()
    plt.show()

    # plot w1
    plt.figure(figsize=(10, 6))
    plt.plot(word1_list, marker='o', linestyle='-', markersize=3)
    plt.xlabel("Event")
    plt.ylabel("w1")
    plt.grid()
    plt.show()

    # plot scatter A vs B
    plt.figure(figsize=(10, 6))
    plt.scatter(scatter_A, scatter_B, alpha=0.5)
    plt.xlabel("Side A")
    plt.ylabel("Side B")
    plt.grid()
    plt.show()

    # plot channel histogram
    plt.figure(figsize=(10, 6))
    plt.bar(bins_channel[:-1], hist_channel, width=1, alpha=0.5, label="Channel")
    plt.xlabel("Channel")
    plt.ylabel("Counts")
    plt.legend()
    plt.grid()
    plt.show()

    # Plot histograms
    plt.figure(figsize=(10, 6))
    plt.bar(bins[:-1], hist_side_A, width=max_bin // n_bins, alpha=0.5, label="Side A")
    plt.bar(bins[:-1], hist_side_B, width=max_bin // n_bins, alpha=0.5, label="Side B")
    plt.xlabel("ADC Value")
    plt.ylabel("Counts")
    plt.legend()
    plt.grid()
    plt.show()

    # plot global time
    plt.figure(figsize=(10, 6))
    plt.plot(global_time, marker='o', linestyle='-', markersize=3)
    plt.xlabel("Event")
    plt.ylabel("Global Time")
    plt.grid()
    plt.show()

# -------------------------------
# set oscilloscope parameters
print("\n --- Setting oscilloscope parameters:")

decimator = 1

res = sdk.SetParameterString(f"board0:/MMCComponents/Oscilloscope_{OSCILLOSCOPE_ID}.data_processing","decode")
res = sdk.SetParameterInteger(f"board0:/MMCComponents/Oscilloscope_{OSCILLOSCOPE_ID}.trigger_level", OSCILLOSCOPE_TRIGGER_LEVEL)
res = sdk.SetParameterString(f"board0:/MMCComponents/Oscilloscope_{OSCILLOSCOPE_ID}.trigger_mode",TRIGGER_MODE)
res = sdk.SetParameterInteger(f"board0:/MMCComponents/Oscilloscope_{OSCILLOSCOPE_ID}.trigger_channel", TRIGGER_CHANNEL)
res = sdk.SetParameterInteger(f"board0:/MMCComponents/Oscilloscope_{OSCILLOSCOPE_ID}.pretrigger", PRETRIGGER_SAMPLES)
res = sdk.SetParameterInteger(f"board0:/MMCComponents/Oscilloscope_{OSCILLOSCOPE_ID}.decimator", decimator)
res = sdk.SetParameterString(f"board0:/MMCComponents/Oscilloscope_{OSCILLOSCOPE_ID}.acq_mode", "blocking")
res = sdk.SetParameterInteger(f"board0:/MMCComponents/Oscilloscope_{OSCILLOSCOPE_ID}.timeout", 3000)
# allocate buffer for oscilloscope
res, buf_osc = sdk.AllocateBuffer(f"board0:/MMCComponents/Oscilloscope_{OSCILLOSCOPE_ID}")
if res != 0:
    print(" ! Failed to allocate buffer for oscilloscope, code:", res)
else:
    print(" - Buffer allocated successfully for oscilloscope")




# ---------------- OSCILLOSCOPE FIGURE ----------------
fig, axs = plt.subplots(2, 1, figsize=(12, 12))

ax_analog  = axs[0]
ax_digital = axs[1]


ax_analog.set_ylabel("ADC")
ax_digital.set_ylabel(f"Digital pulses of CH{DIGITAL_CHANNEL}")
ax_digital.set_xlabel("Time (samples)") 

lines_analog = [] 
for i in CHANNELS_TO_PLOT: 
    line, = ax_analog.plot([], [], label=f"CH{i}") 
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
    res_osc, buf_osc_local = sdk.ReadData(f"board0:/MMCComponents/Oscilloscope_{OSCILLOSCOPE_ID}", buf_osc)

    if res_osc == 0:

        samples = buf_osc_local.info.samples_analog
        channels = buf_osc_local.info.channels

        # -------- ANALOG --------
        xar = [i * decimator for i in range(samples)]

        for ch in CHANNELS_TO_PLOT:
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

                index = DIGITAL_CHANNEL * tracks * samples + d * samples + i
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