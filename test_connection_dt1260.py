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
#OSCILLOSCOPE_TRIGGER_LEVEL = 5000
OSCILLOSCOPE_TRIGGER_LEVEL = 1800
# Digital pulses are asociated to filter output channels of A and B (2 and 3, respectively). 
DIGITAL_CHANNEL = 2 # choose 2 for filter A, 3 for filter B
TRIGGER_CHANNEL = 0 # choose 0 for channel A, 1 for channel B
PRETRIGGER_SAMPLES = 150
TRIGGER_MODE = "analog" #
NUMBER_OF_RECORDS = 10 
OUTPUT_CSV = "output_dt1260.csv"
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

CHANNELS_TO_PLOT = [0,1,2,3] # list of channels to plot (0-3)

# Initialize SDK
sdk = SciSDK()

# Connect to device using your JSON
print("\n")

res = sdk.AddNewDevice("usb:60166", "dt1260", "RegisterFile_dt1260.json", "board0")

if res != 0:
    print(" ! Failed to connect, code:", res)
    exit(1)
print(" - Device connected successfully!")

# -------------------------------
# ---- Load register table ----
print("\n --- Setting registers file:")

table_file = "./table_3_DT1260.txt"

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



    # Extract register short name 
    if name.startswith("REGFILE_0_"):
        param_name = name.replace("REGFILE_0_", "")
        path = f"board0:/MMCComponents/REGFILE_0.{param_name}"
        #print(f"Setting {param_name} at path {path} to value {value_int}")
        err = sdk.SetParameterInteger(path, value_int)
        if err != 0:
            print(f"ERROR setting {param_name}, code {err}")
            continue
        else:
            print(f"{param_name:15s} set to {value_int}")
            continue
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
res = sdk.SetParameterString("board0:/MMCComponents/Oscilloscope_0.trigger_mode",TRIGGER_MODE)
res = sdk.SetParameterInteger("board0:/MMCComponents/Oscilloscope_0.trigger_channel", TRIGGER_CHANNEL)
res = sdk.SetParameterInteger("board0:/MMCComponents/Oscilloscope_0.pretrigger", PRETRIGGER_SAMPLES)
res = sdk.SetParameterInteger("board0:/MMCComponents/Oscilloscope_0.decimator", decimator)
res = sdk.SetParameterString("board0:/MMCComponents/Oscilloscope_0.acq_mode", "blocking")
res = sdk.SetParameterInteger("board0:/MMCComponents/Oscilloscope_0.timeout", 3000)
# allocate buffer for oscilloscope
res, buf_osc = sdk.AllocateBuffer("board0:/MMCComponents/Oscilloscope_0")
if res != 0:
    print(" ! Failed to allocate buffer for oscilloscope, code:", res)
else:
    print(" - Buffer allocated successfully for oscilloscope")


# set Custom Packet parameters
print("\n --- Setting custom packet parameters:")
res = sdk.SetParameterString("board0:/MMCComponents/CP_0.thread", "false")
res = sdk.SetParameterString("board0:/MMCComponents/CP_0.acq_mode", "non-blocking")
res = sdk.SetParameterString("board0:/MMCComponents/CP_0.check_align_word", "check_align_word")
res = sdk.SetParameterString("board0:/MMCComponents/CP_0.data_processing", "decode")
res, check_align_word = sdk.GetParameterString("board0:/MMCComponents/CP_0.check_align_word")
if res != 0:
    print(" ! Failed to get check_align_word parameter for CP, code:", res)
else:    
    print(" - check_align_word parameter for CP:", check_align_word)
res, data_processing = sdk.GetParameterString("board0:/MMCComponents/CP_0.data_processing")
if res != 0:
    print(" ! Failed to get data_processing parameter for CP, code:", res)
else:
    print(" - data_processing parameter for CP:", data_processing)

# allocate buffer for custom packet
res, buf_cus = sdk.AllocateBuffer("board0:/MMCComponents/CP_0", 16000)
if res != 0:
    print(" ! Failed to allocate buffer, code:", res)
    exit(1)
else:
    print(" - Buffer allocated successfully")

res = sdk.ExecuteCommand("board0:/MMCComponents/CP_0.start", "")
if res != 0:
    print(" ! Failed to start acquisition, code:", res)
    exit(1)
else:
    print(" - Acquisition started successfully")


# custom packet recording in ouput CSV file (rewrete if exists)
csv_file = open(OUTPUT_CSV, "w")
csv_file.write("energy_ch1,energy_ch2\n")
for i in range(NUMBER_OF_RECORDS):
    
    # =========================
    # CUSTOM PACKET (ENERGY)
    # =========================
    res_cus, buf_cus_local = sdk.ReadData("board0:/MMCComponents/CP_0", buf_cus)
    if res_cus == 0 and buf_cus_local.info.valid_data > 0:

        for i in range(int(buf_cus_local.info.valid_data)):
            word1 = buf_cus_local.data[i].row[1]
            word2 = buf_cus_local.data[i].row[2]

            energy_ch1 = word2 & 0xFFFF
            energy_ch2 = word1 & 0xFFFF


            csv_file.write(f"{energy_ch1},{energy_ch2}\n")
csv_file.close()
print(f"\nCustom packet data recorded in {OUTPUT_CSV}")

res, pars = sdk.GetAllParameters(
    "board0:/MMCComponents/CP_0"
)

print("res =", res)
print(pars)

for cp in ["CP_0"]:
    path = f"board0:/MMCComponents/{cp}"

    print("\n---", cp)

    sdk.ExecuteCommand(path + ".start", "")
    import time
    time.sleep(2)

    res, v = sdk.GetRegister(path + "/READ_STATUS")
    print("READ_STATUS =", v)

    res, v = sdk.GetRegister(path + "/READ_VALID_WORDS")
    print("VALID_WORDS =", v)



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
for i in CHANNELS_TO_PLOT: 
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