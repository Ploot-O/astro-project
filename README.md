# ASTRO Observatory Control System

ASTRO is a comprehensive control system for the observatory on the roof of Boyer Hall at Arcadia University. It consists of two main components: a Raspberry Pi-based controller (CerebriCaeliV3.py) and a companion Python script (MittensV1.py) that runs on the control computer and sends azimuthal data to the Raspberry Pi.

## CerebriCaeliV3.py

This Python script runs on a Raspberry Pi and controls various aspects of the observatory, including the rotation of the dome, the opening and closing of the shutter, and the synchronization of the dome's position with the target azimuth.

### Features

- **Relay Control**: The script interfaces with a 4-channel relay to control the rotation and shutter motors.
- **Rotary Encoder**: A rotary encoder is used to measure the rotation of the observatory dome with high precision.
- **Configuration Management**: The script reads configuration settings from an INI file, allowing for easy customization.
- **Logging**: Detailed logging is implemented to track the system's operations and any errors or exceptions.
- **Graceful Shutdown**: Signal handlers are in place to allow for a graceful shutdown of the system.
- **Socket Communication**: The script listens for incoming socket connections and accepts azimuthal data from the control computer.
- **Synchronization**: The dome's rotation is synchronized with the target azimuth received from the control computer, taking into account a configurable tolerance threshold and deceleration angle.
- **Home Position**: The script can return the dome to its home position upon a configurable timeout or manual command.

### Classes

1. **Relay**: Handles the control of the 4-channel relay responsible for rotating the dome and opening/closing the shutter.
2. **Encoder**: Interfaces with the rotary encoder to measure the dome's rotation and update the counter value.
3. **Observatory**: Centralizes the control functions for the observatory, including relay operations, synchronization with the target azimuth, and returning to the home position.
4. **Socket**: Handles the communication with the control computer, receiving azimuthal data over a socket connection and updating the observatory's rotation accordingly.

### Usage

1. Install the required dependencies (RPi.GPIO).
2. Configure the settings in the `config.ini` file according to your observatory's specifications.
3. Run the `CerebriCaeliV3.py` script on the Raspberry Pi.
4. Ensure that the companion script `MittensV1.py` is running on the control computer and sending azimuthal data to the correct IP address and port.

## MittensV1.py

This Python script runs on the control computer and sends azimuthal data to the Raspberry Pi running the `CerebriCaeliV3.py` script. It monitors a specified folder for new FITS image files, reads the azimuthal value (CENTAZ) from the FITS header, and sends it to the Raspberry Pi over a socket connection.

### Features

- **Configuration Management**: The script reads configuration settings (IP address, port, folder path) from an INI file, allowing for easy customization.
- **Logging**: Detailed logging is implemented to track the script's operations and any errors or exceptions.
- **FITS Header Reading**: The script uses the `astropy` library to read the azimuthal value (CENTAZ) from the FITS header of new image files.
- **Socket Communication**: The azimuthal value is sent to the Raspberry Pi over a socket connection using the configured IP address and port.
- **File Monitoring**: The script uses the `watchdog` library to monitor the specified folder for new FITS image files and trigger the sending of azimuthal data.
- **Graceful Shutdown**: The script handles `KeyboardInterrupt` and stops the file monitoring gracefully.

### Usage

1. Install the required dependencies (astropy, watchdog).
2. Configure the settings in the `config.ini` file:
  - Set the IP address and port of the Raspberry Pi running `CerebriCaeliV3.py`.
  - Set the folder path to monitor for new FITS image files.
3. Run the `MittensV1.py` script on the control computer.

### Classes and Functions

1. **`send_azimuth`**: Function to handle the socket communication and sending of azimuthal data to the Raspberry Pi.
2. **`FITSEventHandler`**: Custom event handler class that inherits from `FileSystemEventHandler` and implements the `on_created` method. This method checks if the created file is a FITS file, reads the CENTAZ value from the FITS header, and sends it to the Raspberry Pi using the `send_azimuth` function.
3. **`main`**: Main function that sets up the `Observer` and the `FITSEventHandler`, schedules the event handler for the specified folder, and starts the observer. It also includes error handling and graceful shutdown.

## Dependencies

- RPi.GPIO (only for CerebriCaeliV3.py on Raspberry Pi)
- astropy
- watchdog

## Contributing

Contributions to the CerebriCaeli Observatory Control System are welcome! If you encounter any issues or have suggestions for improvements, please open an issue or submit a pull request on the project's GitHub repository.