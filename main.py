from phew import access_point, connect_to_wifi, is_connected_to_wifi, dns, server, logging
from phew.template import render_template
import json
import machine
import os
import utime
import _thread
from edisplay import EPD_2in9_Landscape
import ntptime
import urequests
import ujson
from key import KEY

# https://github.com/simonprickett/phewap

AP_NAME = "clock"
AP_DOMAIN = "clock.net"
AP_TEMPLATE_PATH = "ap_templates"
APP_TEMPLATE_PATH = "app_templates"
WIFI_FILE = "wifi.json"
WIFI_MAX_ATTEMPTS = 3
CONFIG_WAIT = 15  # Wait 15 seconds to start clock

epd = EPD_2in9_Landscape()
epd.Clear(0xff)
epd.fill(0xff)
epd.text("Starting up...", 20, 75, 0x00)
epd.display(epd.buffer)
epd.delay_ms(500)

with open("paragraph.txt", "r") as file:
    role = file.read()

def machine_reset():
    utime.sleep(1)
    print("Resetting...")
    machine.reset()

def setup_mode():
    print("Entering setup mode...")
    def display_qr():
        from edisplay import WIFI_QR
        # epd.Clear(0xff)
        epd.fill(0xff)
        for y, row in enumerate(WIFI_QR):
            for x, pixel in enumerate(row):
                if pixel == 1:
                    epd.pixel(x, y, 0x00)  # Black pixel
        # del WIFI_QR
        epd.text("WiFi Setup Mode..", 75, 10, 0x00)
        epd.text("Scan to get started", 75, 30, 0x00)
        epd.text("Tip: Sometimes you may need to", 10, 60, 0x00)
        epd.text("unplug the device for 10 seconds", 10, 80, 0x00)
        epd.text("after setting up WiFi", 10, 100, 0x00)
        epd.display(epd.buffer)
        epd.delay_ms(2000)

    def ap_index(request):
        if request.headers.get("host").lower() != AP_DOMAIN.lower():
            return render_template(f"{AP_TEMPLATE_PATH}/redirect.html", domain = AP_DOMAIN.lower())

        return render_template(f"{AP_TEMPLATE_PATH}/index.html")

    def ap_configure(request):
        print("Saving wifi credentials...")

        with open(WIFI_FILE, "w") as f:
            json.dump(request.form, f)
            f.close()

        # Reboot from new thread after we have responded to the user.
        _thread.start_new_thread(machine_reset, ())
        return render_template(f"{AP_TEMPLATE_PATH}/configured.html", ssid = request.form["ssid"])
        
    def ap_catch_all(request):
        if request.headers.get("host") != AP_DOMAIN:
            return render_template(f"{AP_TEMPLATE_PATH}/redirect.html", domain = AP_DOMAIN)

        return "Not found.", 404
    
    display_qr()
    server.add_route("/", handler = ap_index, methods = ["GET"])
    server.add_route("/configure", handler = ap_configure, methods = ["POST"])
    server.set_callback(ap_catch_all)

    ap = access_point(AP_NAME)
    ip = ap.ifconfig()[0]
    dns.run_catchall(ip)

def application_mode():
    print("Entering application mode.")
    onboard_led = machine.Pin("LED", machine.Pin.OUT)

    def app_index(request):
        server.cancel_stop()
        epd.Clear(0xff)
        epd.fill(0xff)
        epd.text("Someone has connected!", 10, 10, 0x00)
        epd.text("YAY :)", 10, 30, 0x00)
        epd.display(epd.buffer)
        epd.delay_ms(2000)
        return render_template(f"{APP_TEMPLATE_PATH}/index.html")

    def app_toggle_led(request):
        onboard_led.toggle()
        return "OK"
    
    def app_get_temperature(request):
        # Not particularly reliable but uses built in hardware.
        # Demos how to incorporate senasor data into this application.
        # The front end polls this route and displays the output.
        # Replace code here with something else for a 'real' sensor.
        # Algorithm used here is from:
        # https://www.coderdojotc.org/micropython/advanced-labs/03-internal-temperature/
        sensor_temp = machine.ADC(4)
        reading = sensor_temp.read_u16() * (3.3 / (65535))
        temperature = 27 - (reading - 0.706)/0.001721
        return f"{round(temperature, 1)}"
    
    def app_restart(request):
        _thread.start_new_thread(machine_reset, ())
        return render_template(f"{APP_TEMPLATE_PATH}/restart.html")
    
    def app_reset(request):
        # Deleting the WIFI configuration file will cause the device to reboot as
        # the access point and request new configuration.
        os.remove(WIFI_FILE)
        # Reboot from new thread after we have responded to the user.
        _thread.start_new_thread(machine_reset, ())
        return render_template(f"{APP_TEMPLATE_PATH}/reset.html", access_point_ssid = AP_NAME)

    def app_prompt(request):
        with open("paragraph.txt", "r") as file:
            text = file.read()
        return text
    
    def app_save_prompt(request):
        text = request.form['editedText']
        with open("paragraph.txt", "w") as file:
            file.write(text)
        return render_template(f"{APP_TEMPLATE_PATH}/index.html")
        
    def app_catch_all(request):
        return "Not found.", 404

    server.add_route("/", handler = app_index, methods = ["GET"])
    server.add_route("/toggle", handler = app_toggle_led, methods = ["GET"])
    server.add_route("/temperature", handler = app_get_temperature, methods = ["GET"])
    server.add_route("/reset", handler = app_reset, methods = ["GET"])
    server.add_route("/restart", handler = app_restart, methods = ["GET"])
    server.add_route("/prompt", handler = app_prompt, methods= ["GET"])
    server.add_route("/save_prompt", handler= app_save_prompt, methods= ["POST"])
    # Add other routes for your application...
    server.set_callback(app_catch_all)

def get_current_time():
    current_time = utime.localtime(utime.mktime(utime.localtime()) + 17 * 3600)
    return current_time


def get_formatted_time():
    # Get the current time
    current_time_tuple = get_current_time()

    # Extract the hour and minute from the tuple
    current_hour = current_time_tuple[3]
    ampm = "am"
    if current_hour > 12:
        current_hour = current_hour - 12
        ampm = "pm"
    current_minute = current_time_tuple[4]

    # Format the time as HH:MM
    formatted_time = "{:02d}:{:02d} {}".format(current_hour, current_minute, ampm)

    print("Current time:", formatted_time)
    return formatted_time


def get_time_message(time_of_day):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + KEY
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": role},
            {"role": "user", "content": "The current time is" + str(time_of_day)}
        ],
        "temperature": 0.7
    }

    try:
        resp = urequests.post(
            url,
            headers=headers,
            data=ujson.dumps(data)
        )

        if resp.status_code == 200:
            # Successful response
            print("Request successful")
            # print(resp.text)
        else:
            # Error response
            print("Error:", resp.status_code)
            print(resp.text)
        response = resp.json()
        text = response["choices"][0]["message"]["content"]
        status = response["choices"][0]["finish_reason"]

    except Exception as e:
        print("Error:", e)
        text = "Error: " + str(e)
        status = "Fail"
    return text, status
    
def format_message(input_str, max_chars):
    lines = []
    current_line = ""

    def add_line(line):
        nonlocal lines
        lines.append(line)

    for word in input_str.split():
        if current_line and len(current_line) + len(word) + 1 <= max_chars:
            # Check if adding the next word exceeds the max_chars limit
            current_line += ' ' + word
            if "." in word:
                add_line(current_line)
                current_line = ""
        elif not current_line and len(word) <= max_chars:
            # Check if the first word itself is within the max_chars limit
            current_line = word
        else:
            # Add the current line to the lines list and start a new line with the current word
            add_line(current_line)
            current_line = word
            
        

    # Add the last line if there's any content left
    if current_line:
        add_line(current_line)

    return lines
    
def display(lines, time):
    epd.fill(0xff)
    y = 30
    for line in lines:
        epd.text(line, 10, y, 0x00)
        y = y + 20
    epd.text(time, 230, 10, 0x00)
    epd.display(epd.buffer)
    epd.delay_ms(2000)


# Figure out which mode to start up in...
logging.info("Trying wifi connection")
setup = True
try:
    os.stat(WIFI_FILE)

    # File was found, attempt to connect to wifi...
    with open(WIFI_FILE) as f:
        wifi_current_attempt = 1
        wifi_credentials = json.load(f)
        
        while (wifi_current_attempt < WIFI_MAX_ATTEMPTS):
            ip_address = connect_to_wifi(wifi_credentials["ssid"], wifi_credentials["password"])

            if is_connected_to_wifi():
                print(f"Connected to wifi, IP address {ip_address}")
                logging.info(f"Connected to wifi, IP address {ip_address}")
                break
            else:
                wifi_current_attempt += 1
                
        if is_connected_to_wifi():
            application_mode()
            epd.Clear(0xff)
            epd.fill(0xff)
            epd.text(f"Connect to device from", 10, 10, 0x00)
            epd.text(f"a browser at {ip_address}", 10, 30, 0x00)
            epd.text(f"The clock will automatically", 10, 60, 0x00)
            epd.text(f"startup in {CONFIG_WAIT} seconds", 10, 80, 0x00)
            epd.display(epd.buffer)
            epd.delay_ms(500)
            setup = False
        else:
            
            # Bad configuration, delete the credentials file, reboot
            # into setup mode to get new credentials from the user.
            print("Bad wifi connection!")
            print(wifi_credentials)
            logging.error("Bad Wifi connection")
            os.remove(WIFI_FILE)
            machine_reset()

except Exception as e:
    # Either no wifi configuration file found, or something went wrong, 
    # so go into setup mode.
    logging.error(f"Error: {e}, going into setup mode")
    setup_mode()

try:
    if setup:
        server.run()
    else:
        server.run(wait=CONFIG_WAIT)
except Exception as e:
    logging.error(f"Error: {e} with servers")
    epd.Clear(0xff)
    epd.fill(0xff)
    epd.text(f"Server Error: {e}", 10, 10, 0x00)
    epd.display(epd.buffer)
    epd.delay_ms(500)

# The LED will indicate internet connection
try:
    ntptime.settime()
    # Get the current time
    current_time = get_formatted_time()
    
    # Get poem from openai
    message, status = get_time_message(current_time)
    
    # Format message to wrap lines
    lines = format_message(message, 30)

    # Update the display with the message
    display(lines, current_time)
    utime.sleep(3)
        
    try:
        while True:
            remaining_seconds = 60 - get_current_time()[5]
            print(remaining_seconds)
            utime.sleep(remaining_seconds)
                
            # Get the current time
            current_time = get_formatted_time()
            
            # Get poem from openai
            message, status = get_time_message(current_time)
            
            # Format message to wrap lines
            lines = format_message(message, 30)

            # Update the display with the message
            display(lines, current_time)

    except KeyboardInterrupt:
        # Handle keyboard interrupt (Ctrl+C) to exit the loop gracefully
        pass
except KeyboardInterrupt:
    machine.reset()
except Exception as e:
    print(f"Error: {e}")
    logging.error(str(e))
    epd.Clear(0xff)
    epd.fill(0xff)
    epd.text("Something went wrong, restarting", 10, 10, 0x00)
    epd.display(epd.buffer)
    epd.delay_ms(500)
    machine.reset()